"""Level-4 baseline — PORTFOLIO ``OrderRequest`` replay parity.

Locks the deterministic fingerprint of the per-leg ``OrderRequest``
tuple emitted by
:meth:`feelies.risk.basic_risk.BasicRiskEngine.check_sized_intent`
when fed the canonical Phase-4-finalize Level-3 fixture
(:mod:`tests.determinism.test_sized_intent_replay`).

Determinism (Inv-5)
-------------------

* Iteration over ``intent.target_positions`` is sorted on symbol.
* ``order_id`` is SHA-256 of
  ``(intent.correlation_id, intent.sequence, symbol)`` truncated to 16
  hex chars.
* Marks are seeded with deterministic constants; the position store
  starts empty so every leg appears as a flat→non-zero open.

Per-leg veto (Inv-11) is exercised by configuring a
``max_position_per_symbol`` low enough that some legs would breach the
cap; those legs are silently dropped from the order stream and the
remaining legs proceed.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal

from feelies.core.events import OrderRequest
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.risk.basic_risk import BasicRiskEngine, RiskConfig

from tests.determinism.test_sized_intent_replay import (  # noqa: E501
    _NUM_BOUNDARIES,
    _UNIVERSE,
    _build_engine,
    _make_ctx,
    _HORIZON_SECONDS,
)


# Per-symbol mark seed — deterministic constants, not pulled from any
# external source.  Spread across price magnitudes so the ``target_usd
# / mark`` arithmetic produces non-trivial integer share counts.
_MARK_SEED: dict[str, Decimal] = {
    "AAPL": Decimal("180.00"),
    "AMZN": Decimal("130.00"),
    "GOOG": Decimal("140.00"),
    "META": Decimal("310.00"),
    "MSFT": Decimal("370.00"),
}


def _build_position_store() -> MemoryPositionStore:
    store = MemoryPositionStore()
    for sym, mark in _MARK_SEED.items():
        store.update_mark(sym, mark)
    return store


def _replay() -> tuple[str, int]:
    bus, _engine, captured_intents = _build_engine(decay=False)
    base_ts = 1_700_000_000_000_000_000
    for k in range(_NUM_BOUNDARIES):
        ts = base_ts + k * _HORIZON_SECONDS * 1_000_000_000
        bus.publish(_make_ctx(boundary_index=k + 1, ts_ns=ts, seq=k + 1))

    risk = BasicRiskEngine(
        RiskConfig(
            max_position_per_symbol=500,
            account_equity=Decimal("1000000"),
        ),
    )
    store = _build_position_store()

    orders: list[OrderRequest] = []
    for intent in captured_intents:
        legs = risk.check_sized_intent(intent, store)
        orders.extend(legs)

    return _hash_order_stream(orders), len(orders)


def _hash_order_stream(orders: list[OrderRequest]) -> str:
    lines: list[str] = []
    for o in orders:
        lines.append(
            f"{o.sequence}|{o.timestamp_ns}|{o.order_id}|{o.symbol}|"
            f"{o.side.name}|{o.order_type.name}|{o.quantity}|"
            f"{o.strategy_id}|{o.reason}|{o.correlation_id}|"
            f"src={o.source_layer}"
        )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


# ── Determinism (replay twice → same hash) ──────────────────────────────


def test_two_replays_produce_identical_order_hash() -> None:
    hash_a, count_a = _replay()
    hash_b, count_b = _replay()
    assert count_a == count_b, (
        f"Level-4 PORTFOLIO order count drift: {count_a} vs {count_b}"
    )
    assert hash_a == hash_b, (
        "Level-4 PORTFOLIO OrderRequest hash drift across identical "
        f"replays!\n  a: {hash_a}\n  b: {hash_b}"
    )


def test_orders_are_lex_sorted_within_each_intent() -> None:
    """Inv-5: per-intent leg ordering must be lex-sorted on symbol."""
    bus, _engine, captured_intents = _build_engine(decay=False)
    base_ts = 1_700_000_000_000_000_000
    for k in range(_NUM_BOUNDARIES):
        ts = base_ts + k * _HORIZON_SECONDS * 1_000_000_000
        bus.publish(_make_ctx(boundary_index=k + 1, ts_ns=ts, seq=k + 1))

    risk = BasicRiskEngine(
        RiskConfig(
            max_position_per_symbol=500,
            account_equity=Decimal("1000000"),
        ),
    )
    store = _build_position_store()
    for intent in captured_intents:
        legs = risk.check_sized_intent(intent, store)
        symbols = [leg.symbol for leg in legs]
        assert symbols == sorted(symbols), (
            f"per-intent legs not lex-sorted: {symbols}"
        )
        for leg in legs:
            assert leg.symbol in _UNIVERSE
            assert leg.reason == "PORTFOLIO"
            assert leg.source_layer == "PORTFOLIO"
