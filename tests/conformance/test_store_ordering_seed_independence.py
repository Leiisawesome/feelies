"""R8 — position-store iteration order is seed-independent.

``MemoryPositionStore`` keys by insertion order (a dict).  A set-based
iteration would make fill distribution a function of PYTHONHASHSEED (G08).
"""

from __future__ import annotations

from decimal import Decimal

from feelies.portfolio.memory_position_store import MemoryPositionStore


def test_position_store_ordering_is_seed_independent() -> None:
    store = MemoryPositionStore()
    order = ("ZZZ", "AAA", "MNO")
    for symbol in order:
        store.update(symbol, 1, Decimal("10"))
    keys = list(store.all_positions())
    assert keys, "store reported no positions — the ordering check is vacuous"
    assert keys == list(order), (
        f"all_positions iteration {keys} != insertion order {list(order)}; "
        "a hash-ordered container would make replay a function of PYTHONHASHSEED"
    )
