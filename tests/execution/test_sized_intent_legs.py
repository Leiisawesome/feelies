"""Construction of a ``SizedPositionIntent`` leg, independent of admission.

This logic was interleaved with the risk verdict loop in
``risk/sized_intent_orders.py``, so it could only be reached through a risk
engine.  Split out, the construction rules are testable on their own — and they
are the rules that decide how much of an approved target actually gets traded.
"""

from __future__ import annotations

from decimal import Decimal

from feelies.core.events import (
    OrderType,
    Side,
    SizedPositionIntent,
    TargetPosition,
)
from feelies.execution.sized_intent_legs import plan_leg, rescale_leg, resolve_mark
from feelies.portfolio.memory_position_store import MemoryPositionStore

_SYMBOL = "AAPL"


def _intent(**targets: float) -> SizedPositionIntent:
    return SizedPositionIntent(
        timestamp_ns=1_000,
        correlation_id="corr-1",
        sequence=7,
        strategy_id="sig_demo_v1",
        target_positions={
            sym: TargetPosition(symbol=sym, target_usd=usd) for sym, usd in targets.items()
        },
    )


# ── Mark resolution ─────────────────────────────────────────────────────


def test_live_mark_is_preferred_over_cost_basis() -> None:
    positions = MemoryPositionStore()
    positions.update(_SYMBOL, 100, Decimal("150.00"))
    positions.update_mark(_SYMBOL, Decimal("160.00"))

    assert resolve_mark(_SYMBOL, positions.get(_SYMBOL), positions) == Decimal("160.00")


def test_cost_basis_is_the_boot_time_fallback() -> None:
    """Before any quote has flowed, the entry price is the only mark there is."""
    positions = MemoryPositionStore()
    positions.update(_SYMBOL, 100, Decimal("150.00"))

    assert resolve_mark(_SYMBOL, positions.get(_SYMBOL), positions) == Decimal("150.00")


def test_no_mark_returns_zero_so_the_leg_is_skipped() -> None:
    """Unpriceable means untradeable — the caller must skip, not guess (Inv-11)."""
    positions = MemoryPositionStore()

    assert resolve_mark("NEVER_SEEN", positions.get("NEVER_SEEN"), positions) == Decimal("0")


def test_raising_mark_accessor_falls_back_instead_of_propagating() -> None:
    """A broken mark feed must degrade, never raise into the risk path."""

    class _Exploding(MemoryPositionStore):
        def latest_mark(self, symbol: str) -> Decimal | None:
            raise RuntimeError("mark feed down")

    positions = _Exploding()
    positions.update(_SYMBOL, 100, Decimal("150.00"))

    assert resolve_mark(_SYMBOL, positions.get(_SYMBOL), positions) == Decimal("150.00")


# ── Leg construction ────────────────────────────────────────────────────


def test_target_converts_to_shares_and_deltas_against_the_position() -> None:
    positions = MemoryPositionStore()
    positions.update(_SYMBOL, 40, Decimal("100.00"))
    positions.update_mark(_SYMBOL, Decimal("100.00"))

    leg = plan_leg(_intent(AAPL=10_000.0), _SYMBOL, positions)

    assert leg is not None
    # 10_000 / 100 = 100 target shares, already holding 40 -> buy 60.
    assert leg.order.side is Side.BUY
    assert leg.order.quantity == 60
    assert leg.signed_quantity == 60
    assert leg.current_quantity == 40
    assert leg.order.order_type is OrderType.MARKET
    assert leg.order.source_layer == "PORTFOLIO"


def test_a_target_below_the_position_sells_the_difference() -> None:
    positions = MemoryPositionStore()
    positions.update(_SYMBOL, 100, Decimal("100.00"))
    positions.update_mark(_SYMBOL, Decimal("100.00"))

    leg = plan_leg(_intent(AAPL=3_000.0), _SYMBOL, positions)

    assert leg is not None
    assert leg.order.side is Side.SELL
    assert leg.order.quantity == 70
    assert leg.signed_quantity == -70


def test_target_already_met_plans_nothing() -> None:
    """No delta means no order — the intent is satisfied by the standing book."""
    positions = MemoryPositionStore()
    positions.update(_SYMBOL, 100, Decimal("100.00"))
    positions.update_mark(_SYMBOL, Decimal("100.00"))

    assert plan_leg(_intent(AAPL=10_000.0), _SYMBOL, positions) is None


def test_unpriceable_symbol_plans_nothing() -> None:
    positions = MemoryPositionStore()

    assert plan_leg(_intent(AAPL=10_000.0), _SYMBOL, positions) is None


def test_share_conversion_rounds_half_up_not_toward_zero() -> None:
    """Decimal ROUND_HALF_UP, never float truncation (Inv-5)."""
    positions = MemoryPositionStore()
    positions.update_mark(_SYMBOL, Decimal("2.00"))

    # 5.00 / 2.00 = 2.5 -> 3, not 2.
    leg = plan_leg(_intent(AAPL=5.0), _SYMBOL, positions)
    assert leg is not None and leg.order.quantity == 3


def test_order_id_is_derived_from_intent_provenance() -> None:
    """Same intent replays to the same id (Inv-5)."""
    positions = MemoryPositionStore()
    positions.update_mark(_SYMBOL, Decimal("100.00"))

    a = plan_leg(_intent(AAPL=1_000.0), _SYMBOL, positions)
    b = plan_leg(_intent(AAPL=1_000.0), _SYMBOL, positions)

    assert a is not None and b is not None
    assert a.order.order_id == b.order.order_id


# ── Rescaling ───────────────────────────────────────────────────────────


def test_rescale_keeps_the_same_order_id() -> None:
    """A scale-down is one decision resized, not a second order."""
    positions = MemoryPositionStore()
    positions.update_mark(_SYMBOL, Decimal("100.00"))
    leg = plan_leg(_intent(AAPL=10_000.0), _SYMBOL, positions)
    assert leg is not None

    scaled = rescale_leg(leg, 0.5)

    assert scaled is not None
    assert scaled.order.quantity == 50
    assert scaled.order.order_id == leg.order.order_id
    assert scaled.order.side is leg.order.side
    assert scaled.mark == leg.mark
    assert scaled.current_quantity == leg.current_quantity


def test_rescale_to_zero_drops_the_leg_rather_than_flooring_to_one() -> None:
    """Forcing a one-share order would trade purely to satisfy rounding."""
    positions = MemoryPositionStore()
    positions.update_mark(_SYMBOL, Decimal("100.00"))
    leg = plan_leg(_intent(AAPL=200.0), _SYMBOL, positions)
    assert leg is not None and leg.order.quantity == 2

    assert rescale_leg(leg, 0.0) is None
    assert rescale_leg(leg, 0.2) is None  # 2 * 0.2 = 0.4 -> 0


def test_rescale_by_one_returns_the_same_leg() -> None:
    positions = MemoryPositionStore()
    positions.update_mark(_SYMBOL, Decimal("100.00"))
    leg = plan_leg(_intent(AAPL=10_000.0), _SYMBOL, positions)
    assert leg is not None

    assert rescale_leg(leg, 1.0) is leg


def test_rescale_rounds_half_up() -> None:
    positions = MemoryPositionStore()
    positions.update_mark(_SYMBOL, Decimal("100.00"))
    leg = plan_leg(_intent(AAPL=500.0), _SYMBOL, positions)
    assert leg is not None and leg.order.quantity == 5

    # 5 * 0.5 = 2.5 -> 3
    scaled = rescale_leg(leg, 0.5)
    assert scaled is not None and scaled.order.quantity == 3
