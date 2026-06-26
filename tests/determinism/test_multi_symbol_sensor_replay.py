"""Multi-symbol L1 baseline — cross-symbol ``SensorReading`` interleave (P1 #8).

Every existing L1/L2/L3 sensor & snapshot baseline replays a **single-symbol**
fixture (``frozenset({"AAPL"})``), so cross-symbol *emission interleave* —
the order in which readings for different symbols hit the bus, and the
sequence numbers they draw — is unpinned.  A bug that grouped emission by
symbol (instead of preserving per-quote interleave) or that leaked one
symbol's sequence counter into another's would not be caught.

This baseline replays a deterministic **round-robin** quote stream across three
symbols (AAPL, MSFT, NVDA) through a real :class:`SensorRegistry` and hashes
the ``SensorReading`` stream with the same serializer as the single-symbol L1
baseline (``_hash_reading_stream`` — it includes ``symbol`` and ``sequence``),
so the cross-symbol interleave and sequence allocation are now locked.
"""

from __future__ import annotations

from decimal import Decimal

from feelies.bus.event_bus import EventBus
from feelies.core.events import NBBOQuote, SensorReading
from feelies.core.identifiers import SequenceGenerator
from feelies.sensors.impl.micro_price import MicroPriceSensor
from feelies.sensors.impl.ofi_ewma import OFIEwmaSensor
from feelies.sensors.registry import SensorRegistry
from feelies.sensors.spec import SensorSpec
from tests.determinism.test_sensor_reading_replay import _hash_reading_stream

# Ordered so the round-robin interleave is a fixed function of the tuple.
_SYMBOLS: tuple[str, ...] = ("AAPL", "MSFT", "NVDA")
_BASE_TS = 1_700_000_000_000_000_000
_DT_NS = 100_000_000  # 100 ms between quotes
_ROUNDS = 8

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
)

# Deterministic per-symbol price anchors so the three symbols produce distinct
# sensor values (and a cross-symbol value swap would flip the hash).
_BASE_PRICE: dict[str, Decimal] = {
    "AAPL": Decimal("180.00"),
    "MSFT": Decimal("370.00"),
    "NVDA": Decimal("120.00"),
}


def _quote(symbol: str, round_idx: int, ts_ns: int, seq: int) -> NBBOQuote:
    bid = _BASE_PRICE[symbol] + Decimal(round_idx) * Decimal("0.01")
    ask = bid + Decimal("0.02")
    # Sizes shift deterministically so ofi_ewma sees real order-flow imbalance.
    bid_size = 100 + (round_idx % 3) * 10
    ask_size = 100 + ((round_idx + 1) % 4) * 10
    return NBBOQuote(
        timestamp_ns=ts_ns,
        correlation_id=f"q:{symbol}:{seq}",
        sequence=seq,
        symbol=symbol,
        bid=bid,
        ask=ask,
        bid_size=bid_size,
        ask_size=ask_size,
        exchange_timestamp_ns=ts_ns,
    )


def _replay() -> tuple[str, int]:
    bus = EventBus()
    captured: list[SensorReading] = []
    bus.subscribe(SensorReading, captured.append)  # type: ignore[arg-type]

    registry = SensorRegistry(
        bus=bus,
        sequence_generator=SequenceGenerator(),
        symbols=frozenset(_SYMBOLS),
    )
    for spec in _SENSOR_SPECS:
        registry.register(spec)

    qseq = 0
    for round_idx in range(_ROUNDS):
        for offset, symbol in enumerate(_SYMBOLS):
            qseq += 1
            ts = _BASE_TS + (round_idx * len(_SYMBOLS) + offset) * _DT_NS
            bus.publish(_quote(symbol, round_idx, ts, qseq))

    return _hash_reading_stream(captured), len(captured)


# Locked multi-symbol L1 baseline.  Re-baseline only with an intentional
# sensor/emission change, justified in the commit.
EXPECTED_MULTI_SYMBOL_READING_HASH = (
    "dc0610868a34ee9c3a7e90c486b0af81154b44d1abe3ab20c9265e50abbff938"
)
EXPECTED_MULTI_SYMBOL_READING_COUNT = 48


def test_multi_symbol_reading_stream_matches_locked_baseline() -> None:
    actual_hash, actual_count = _replay()
    assert actual_count == EXPECTED_MULTI_SYMBOL_READING_COUNT, (
        f"multi-symbol reading count drift: expected "
        f"{EXPECTED_MULTI_SYMBOL_READING_COUNT}, got {actual_count}"
    )
    assert actual_hash == EXPECTED_MULTI_SYMBOL_READING_HASH, (
        "Multi-symbol L1 SensorReading hash drift!\n"
        f"  Expected: {EXPECTED_MULTI_SYMBOL_READING_HASH}\n"
        f"  Actual:   {actual_hash}\n"
        "If intentional, update the constant in the same commit and justify."
    )


def test_two_replays_produce_identical_reading_hash() -> None:
    hash_a, count_a = _replay()
    hash_b, count_b = _replay()
    assert count_a == count_b
    assert hash_a == hash_b


def test_stream_interleaves_all_symbols() -> None:
    """Guard: the stream must actually interleave (not group by symbol).

    If readings were grouped per symbol the first three readings would all be
    one symbol; round-robin publication must instead surface every symbol
    within the first round.
    """
    bus = EventBus()
    captured: list[SensorReading] = []
    bus.subscribe(SensorReading, captured.append)  # type: ignore[arg-type]
    registry = SensorRegistry(
        bus=bus,
        sequence_generator=SequenceGenerator(),
        symbols=frozenset(_SYMBOLS),
    )
    for spec in _SENSOR_SPECS:
        registry.register(spec)
    qseq = 0
    for round_idx in range(_ROUNDS):
        for offset, symbol in enumerate(_SYMBOLS):
            qseq += 1
            ts = _BASE_TS + (round_idx * len(_SYMBOLS) + offset) * _DT_NS
            bus.publish(_quote(symbol, round_idx, ts, qseq))

    assert {r.symbol for r in captured} == set(_SYMBOLS), "not all symbols emitted readings"
    # Within the first round every symbol must appear before any symbol repeats
    # a *round* — i.e. the readings are interleaved, not symbol-grouped.
    first_round_symbols = [r.symbol for r in captured[: len(_SYMBOLS) * len(_SENSOR_SPECS)]]
    assert set(first_round_symbols) == set(_SYMBOLS), (
        f"first-round readings not interleaved across symbols: {first_round_symbols}"
    )
