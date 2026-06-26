"""Unit tests for EventSerializer protocol."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.events import Event, MetricEvent, MetricType, NBBOQuote, Trade
from feelies.core.serialization import (
    EventSerializer,
    JsonLineEventSerializer,
    dict_to_event,
    event_to_dict,
)


class TestEventSerializerProtocol:
    """Tests for EventSerializer protocol (structural typing)."""

    def test_protocol_requires_serialize_and_deserialize(self) -> None:
        """A minimal implementation satisfies the protocol."""

        class MinimalSerializer:
            def serialize(self, event: Event) -> bytes:
                return b"minimal"

            def deserialize(self, data: bytes) -> Event:
                raise ValueError("not implemented")

        impl: EventSerializer = MinimalSerializer()
        assert impl.serialize(Event(timestamp_ns=0, correlation_id="", sequence=0)) == b"minimal"


def _quote() -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=100,
        correlation_id="cid-q",
        sequence=1,
        symbol="AAPL",
        bid=Decimal("150.01"),
        ask=Decimal("150.03"),
        bid_size=90,
        ask_size=120,
        bid_exchange=11,
        ask_exchange=12,
        exchange_timestamp_ns=100,
        conditions=(1, 2, 3),
        indicators=(4,),
        sequence_number=7,
        tape=3,
        participant_timestamp_ns=99,
        trf_timestamp_ns=None,
        received_ns=101,
    )


def _trade() -> Trade:
    return Trade(
        timestamp_ns=200,
        correlation_id="cid-t",
        sequence=2,
        symbol="MSFT",
        price=Decimal("410.55"),
        size=500,
        exchange=4,
        trade_id="abc",
        exchange_timestamp_ns=200,
        conditions=(),
        decimal_size=None,
        sequence_number=8,
        tape=1,
        trf_id=None,
        trf_timestamp_ns=None,
        participant_timestamp_ns=None,
        correction=None,
        received_ns=None,
    )


class TestJsonLineEventSerializer:
    """Concrete serializer: round-trip, bit-determinism, type fidelity (ING-05)."""

    def test_round_trip_quote(self) -> None:
        s = JsonLineEventSerializer()
        q = _quote()
        assert s.deserialize(s.serialize(q)) == q

    def test_round_trip_trade(self) -> None:
        s = JsonLineEventSerializer()
        t = _trade()
        assert s.deserialize(s.serialize(t)) == t

    def test_bit_deterministic(self) -> None:
        s = JsonLineEventSerializer()
        q = _quote()
        assert s.serialize(q) == s.serialize(q)
        # A fresh, equal instance serializes to identical bytes.
        assert s.serialize(_quote()) == s.serialize(q)

    def test_decimal_fidelity_preserved(self) -> None:
        s = JsonLineEventSerializer()
        d = event_to_dict(_quote())
        assert d["bid"] == "150.01"  # stringified, not float
        back = dict_to_event(d)
        assert isinstance(back.bid, Decimal) and back.bid == Decimal("150.01")
        assert s.deserialize(s.serialize(_quote())).bid == Decimal("150.01")

    def test_tuple_conditions_round_trip_as_tuple(self) -> None:
        back = dict_to_event(event_to_dict(_quote()))
        assert back.conditions == (1, 2, 3)
        assert isinstance(back.conditions, tuple)

    def test_serialize_rejects_non_market_event(self) -> None:
        s = JsonLineEventSerializer()
        m = MetricEvent(
            timestamp_ns=1,
            correlation_id="c",
            sequence=1,
            layer="kernel",
            name="x",
            value=1.0,
            metric_type=MetricType.COUNTER,
        )
        with pytest.raises(ValueError, match="only persists"):
            s.serialize(m)

    def test_deserialize_rejects_corrupt_bytes(self) -> None:
        s = JsonLineEventSerializer()
        with pytest.raises(ValueError):
            s.deserialize(b"{not json")

    def test_deserialize_rejects_unknown_type(self) -> None:
        with pytest.raises(ValueError, match="unknown or missing event __type__"):
            dict_to_event({"__type__": "Bogus", "symbol": "AAPL"})

    def test_serialized_dict_carries_schema_version(self) -> None:
        d = event_to_dict(_quote())
        assert d["__schema_version__"] == 1

    def test_legacy_record_without_schema_version_loads(self) -> None:
        # Records written before versioning carry no __schema_version__ and
        # must still deserialize (== v1) — DiskEventCache backward-compat.
        d = event_to_dict(_quote())
        del d["__schema_version__"]
        assert dict_to_event(d) == _quote()

    def test_unsupported_schema_version_rejected(self) -> None:
        d = event_to_dict(_quote())
        d["__schema_version__"] = 999
        with pytest.raises(ValueError, match="unsupported event __schema_version__"):
            dict_to_event(d)

    def test_forward_schema_unknown_field_is_dropped(self) -> None:
        # A record from a newer build with an extra additive field must
        # round-trip to an equal event, not raise (audit P1-2).
        d = event_to_dict(_quote())
        d["future_field_added_later"] = 42
        assert dict_to_event(d) == _quote()

    def test_missing_required_field_raises_value_error(self) -> None:
        # Corrupt record (required field absent) surfaces as ValueError per
        # the deserialize contract, not a raw TypeError (audit P1-2).
        d = event_to_dict(_quote())
        del d["symbol"]
        with pytest.raises(ValueError, match="cannot reconstruct"):
            dict_to_event(d)
