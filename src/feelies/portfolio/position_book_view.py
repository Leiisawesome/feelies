"""Read-only quantity view of the engine-7 position book.

S-05 closed silent flattening on a failed lookup. This view makes the
S-05 failure shape ``current_positions[s] = 0.0`` unconstructible: the
type has no ``__setitem__``, and :meth:`as_mapping` returns
``MappingProxyType``.
"""

from __future__ import annotations

from feelies.core.position_book_view import (
    PositionBookView as PositionBookView,
    _ReadableBook as _ReadableBook,
)
