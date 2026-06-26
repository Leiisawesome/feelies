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

import json
from decimal import Decimal
from typing import Any, Protocol

from feelies.core.events import Event, NBBOQuote, Trade

_TYPE_QUOTE = "NBBOQuote"
_TYPE_TRADE = "Trade"

# On-disk event schema version.  Written into every serialized record and
# validated on load so schema evolution is explicit (Inv-7) rather than a
# silent ``TypeError`` from a future field.  Records written before this tag
# existed carry no ``__schema_version__`` key and are treated as version 1,
# so existing disk caches remain loadable (DiskEventCache backward-compat).
_SCHEMA_VERSION = 1


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


def event_to_dict(event: NBBOQuote | Trade) -> dict[str, Any]:
    """Serialize a frozen market event to a JSON-safe dict.

    Decimal fields are converted to strings to preserve precision (Inv-5).
    Tuple fields are converted to lists for JSON compatibility.  Field
    iteration order follows ``__dataclass_fields__`` (definition order),
    which is stable across processes — the basis of bit-determinism.
    """
    d: dict[str, Any] = {
        "__type__": _TYPE_QUOTE if isinstance(event, NBBOQuote) else _TYPE_TRADE,
        "__schema_version__": _SCHEMA_VERSION,
    }
    for name in event.__dataclass_fields__:
        val = getattr(event, name)
        if isinstance(val, Decimal):
            d[name] = str(val)
        elif isinstance(val, tuple):
            d[name] = list(val)
        else:
            d[name] = val
    return d


def dict_to_event(d: dict[str, Any]) -> NBBOQuote | Trade:
    """Deserialize a dict back into a frozen ``NBBOQuote`` or ``Trade``.

    Type-string matching is intentionally **substring-based** so
    annotations such as ``"Decimal"``, ``"Decimal | None"``,
    ``"tuple[int, ...]"``, and any future ``"tuple[int, ...] | None"``
    are all reverse-mapped correctly without depending on the exact
    spelling.  ``from __future__ import annotations`` makes every
    dataclass field type a string at this layer, so we cannot rely on
    runtime ``isinstance`` of the declared type.

    Forward-compatible by design: a record from a newer build that carries
    fields this build does not know about is reconstructed by ignoring the
    unknown fields (additive evolution), rather than raising.  An unknown
    ``__schema_version__`` *is* rejected, since a version bump signals a
    non-additive change this build cannot safely interpret.

    Raises ``ValueError`` if ``__type__`` is missing/unknown, if the
    ``__schema_version__`` is unsupported, or if the record cannot be
    reconstructed into the target event (e.g. a required field is absent).
    """
    work = dict(d)
    type_tag = work.pop("__type__", None)
    # Absent tag ⇒ legacy record written before versioning existed (== v1).
    schema_version = work.pop("__schema_version__", _SCHEMA_VERSION)
    if schema_version != _SCHEMA_VERSION:
        raise ValueError(
            f"unsupported event __schema_version__: {schema_version!r} "
            f"(this build reads v{_SCHEMA_VERSION})"
        )
    if type_tag == _TYPE_QUOTE:
        cls: type[NBBOQuote | Trade] = NBBOQuote
    elif type_tag == _TYPE_TRADE:
        cls = Trade
    else:
        raise ValueError(f"unknown or missing event __type__: {type_tag!r}")

    for name, field_obj in cls.__dataclass_fields__.items():
        if name not in work:
            continue
        val = work[name]
        ft = field_obj.type
        ft_str = ft if isinstance(ft, str) else getattr(ft, "__name__", str(ft))
        if "Decimal" in ft_str:
            if val is not None:
                work[name] = Decimal(str(val))
        elif "tuple" in ft_str:
            # Any tuple field (tuple[int, ...], tuple[str, ...], …): JSON
            # decodes tuples as lists, so restore tuple identity for every
            # element type, not just int (audit P2-1 — prevents list/tuple
            # drift breaking Inv-5 round-trip equality).
            if isinstance(val, list):
                work[name] = tuple(val)

    # Drop any field this build does not recognise (forward-schema record)
    # so reconstruction never raises on an unexpected keyword.
    known = cls.__dataclass_fields__
    clean = {k: v for k, v in work.items() if k in known}
    try:
        return cls(**clean)
    except TypeError as exc:
        # Missing required field / wrong arity: corrupt record per the
        # deserialize contract — surface as ValueError, not TypeError.
        raise ValueError(f"cannot reconstruct {type_tag} event: {exc}") from exc


class JsonLineEventSerializer:
    """Concrete :class:`EventSerializer` — one canonical JSON object per event.

    Bit-deterministic by construction: ``__dataclass_fields__`` iteration
    order is stable, ``json.dumps`` preserves dict insertion order, and
    Decimal/tuple coercion is total.  This is the single source of truth
    for ``NBBOQuote`` / ``Trade`` persistence — :class:`DiskEventCache`
    and any future JSONL writer route through it (audit ING-05).
    """

    def serialize(self, event: Event) -> bytes:
        if not isinstance(event, (NBBOQuote, Trade)):
            raise ValueError(
                f"JsonLineEventSerializer only persists NBBOQuote / Trade, got {type(event).__name__}"
            )
        return json.dumps(event_to_dict(event), default=str).encode("utf-8")

    def deserialize(self, data: bytes) -> Event:
        try:
            obj = json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(f"corrupt event bytes: {exc}") from exc
        if not isinstance(obj, dict):
            raise ValueError(f"expected a JSON object, got {type(obj).__name__}")
        return dict_to_event(obj)
