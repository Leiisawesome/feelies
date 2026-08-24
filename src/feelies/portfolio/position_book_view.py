"""Read-only quantity view of the engine-7 position book.

S-05 closed silent flattening on a failed lookup. This view makes the
S-05 failure shape ``current_positions[s] = 0.0`` unconstructible: the
type has no ``__setitem__``, and :meth:`as_mapping` returns
``MappingProxyType``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from feelies.portfolio.position_store import Position


class _ReadableBook(Protocol):
    def all_positions(self) -> Mapping[str, Position]: ...


@dataclass(frozen=True, slots=True)
class PositionBookView:
    """Frozen read surface over live quantity state.

    Writers keep the underlying store. This object exposes only
    :meth:`get`, :meth:`as_mapping`, and ``in``. ``all_positions`` is a
    compatibility read for existing ``Orchestrator.position_store``
    consumers that iterate :class:`Position` values; it returns
    ``MappingProxyType``, not a mutable dict.
    """

    _quantities: Callable[[], Mapping[str, float]]
    _positions: Callable[[], Mapping[str, Position]] | None = None

    @classmethod
    def from_store(cls, store: _ReadableBook) -> PositionBookView:
        """Live view over a store that offers ``all_positions``."""

        def quantities() -> Mapping[str, float]:
            all_pos = store.all_positions()
            return {sym: float(pos.quantity) for sym, pos in all_pos.items()}

        def positions() -> Mapping[str, Position]:
            snapshot: Mapping[str, Position] = store.all_positions()
            return snapshot

        return cls(_quantities=quantities, _positions=positions)

    @classmethod
    def from_quantities(cls, quantities: Mapping[str, float]) -> PositionBookView:
        frozen = MappingProxyType({k: float(quantities[k]) for k in sorted(quantities)})
        return cls(_quantities=lambda: frozen)

    def get(self, symbol: str, default: float = 0.0) -> float:
        return float(self._quantities().get(symbol, default))

    def as_mapping(self) -> Mapping[str, float]:
        src = self._quantities()
        return MappingProxyType({k: float(src[k]) for k in sorted(src)})

    def __contains__(self, symbol: object) -> bool:
        if not isinstance(symbol, str):
            return False
        return symbol in self._quantities()

    def all_positions(self) -> Mapping[str, Position]:
        if self._positions is None:
            raise TypeError("this view does not expose Position objects")
        return MappingProxyType(dict(self._positions()))
