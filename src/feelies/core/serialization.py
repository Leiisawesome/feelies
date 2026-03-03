"""Event serialization protocol — durable, type-faithful event encoding.

Foundational infrastructure for the storage layer.  Every event must
be serializable to bytes and reconstructable with full type fidelity:

  - Decimal precision preserved (not float-converted)
  - Enum values round-trip correctly
  - Frozen dataclass fields restored as the correct Event subclass
  - Schema evolution handled explicitly (not silently dropped)

Invariant 5 (deterministic replay) requires that serialization is
bit-deterministic: ``serialize(event)`` always produces identical
bytes for the same event.

Tradeoff: type safety + correctness over serialization speed.
The storage layer is off the critical tick-to-trade path, so
fidelity is prioritized over throughput.
"""

from __future__ import annotations

from typing import Protocol

from feelies.core.events import Event


class EventSerializer(Protocol):
    """Serialize and deserialize typed events with full fidelity.

    Implementations must guarantee:
      1. Round-trip correctness: ``deserialize(serialize(e)) == e``
      2. Bit-determinism: ``serialize(e)`` is identical across calls
      3. Type preservation: Event subclass identity is maintained
      4. Decimal fidelity: no precision loss from float conversion
    """

    def serialize(self, event: Event) -> bytes:
        """Encode an event to bytes.  Output must be bit-deterministic."""
        ...

    def deserialize(self, data: bytes) -> Event:
        """Reconstruct a typed event from bytes.

        Raises ``ValueError`` if the data is corrupt or the event type
        is unknown.
        """
        ...
