"""Deterministic JSON serialization for cached market-data events.

Only ``NBBOQuote`` and ``Trade`` are persisted. Downstream events are
recomputed from that input tape during replay.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Protocol

from feelies.core.events import Event, NBBOQuote, Trade

_TYPE_QUOTE = "NBBOQuote"
_TYPE_TRADE = "Trade"

# Records without a schema tag are version 1.
_SCHEMA_VERSION = 1


class EventSerializer(Protocol):
    """Serialize typed events deterministically and without precision loss."""

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
    # Missing tags identify version-1 records.
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
            # JSON decodes tuples as lists; restore tuple identity.
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
    Decimal/tuple coercion is total.
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
