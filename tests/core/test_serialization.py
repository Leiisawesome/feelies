"""Unit tests for EventSerializer protocol."""

from __future__ import annotations

import pytest

from feelies.core.events import Event
from feelies.core.serialization import EventSerializer


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
