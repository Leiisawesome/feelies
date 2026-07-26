"""A real fill must populate the strategy-slice book, not just the aggregate one.

``StrategyPositionStore`` is the **strategy-slice** book that every slice-scoped
reader depends on:

* the Stage-0 :class:`~feelies.risk.deferral_cap.DeferralCapController` (its
  ``min()`` ceiling is evaluated against ``get()``/``opened_at_ns()``);
* the Stage-0 :class:`~feelies.risk.exit_composer.ExitComposer`;
* the per-alpha budgets in
  :class:`~feelies.alpha.risk_wrapper.AlphaBudgetRiskWrapper`;
* :func:`~feelies.alpha.arbitration.standalone_signal_actionable_for_strategy`,
  which decides whether a directional exit belongs to the alpha emitting it.

It was never written on an **entry** fill.  ``FillAttributionLedger`` documents
its own contract as "orchestrator calls ``record()`` when building each net
order" and step 1 was never implemented, so ``allocate_fill`` always returned
``[]`` for an unknown ``order_id``; the remaining fallback,
``_distribute_fill_to_strategies``, splits across strategies that *already* hold
quantity and returns early when none do — so a slice could never acquire its
first position.  The slice book stayed empty for the whole run and every reader
above saw a permanently flat strategy.

Why no existing test caught it: the Stage-0 suite hand-seeds the store
(``tests/kernel/test_stage0_decouple_wiring.py`` calls
``strategy_positions.update(...)`` directly before asserting the ceiling fires),
so "the whole Stage-0 promise in one path" was verified over a book that the
real fill path never fills.

These tests drive the orchestrator's actual ack-reconciliation path and assert
the slice book is written, that single-strategy attribution is **exact** against
the aggregate book, and that a symbol-net hazard exit is still *not*
self-attributed to one slice.
"""

from __future__ import annotations

from decimal import Decimal

from feelies.alpha.fill_attribution import FillAttributionLedger
from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    OrderType,
    Side,
)
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.portfolio.strategy_position_store import StrategyPositionStore
from feelies.risk.hazard_exit import HAZARD_EXIT_REASON_SPIKE

from tests.kernel.test_orchestrator import _build_orchestrator

_SYMBOL = "AAPL"
_SID = "alpha_1"
_OTHER_SID = "alpha_2"


def _entry_order(
    *,
    order_id: str = "entry-1",
    side: Side = Side.BUY,
    quantity: int = 10,
    strategy_id: str = _SID,
    reason: str = "",
) -> OrderRequest:
    """An ordinary signal-path entry: carries a strategy_id, no forced reason."""
    return OrderRequest(
        timestamp_ns=1000,
        correlation_id="cid-entry",
        sequence=1,
        order_id=order_id,
        symbol=_SYMBOL,
        side=side,
        order_type=OrderType.MARKET,
        quantity=quantity,
        strategy_id=strategy_id,
        reason=reason,
    )


def _fill(
    order: OrderRequest,
    *,
    quantity: int | None = None,
    price: Decimal = Decimal("150.00"),
    fees: Decimal = Decimal("0.10"),
    timestamp_ns: int = 2000,
) -> OrderAck:
    return OrderAck(
        timestamp_ns=timestamp_ns,
        correlation_id=order.correlation_id,
        sequence=order.sequence,
        order_id=order.order_id,
        symbol=order.symbol,
        status=OrderAckStatus.FILLED,
        filled_quantity=quantity if quantity is not None else order.quantity,
        fill_price=price,
        fees=fees,
    )


def _orchestrator(
    positions: MemoryPositionStore,
    slices: StrategyPositionStore,
    *,
    ledger: FillAttributionLedger | None = None,
    with_ledger: bool = True,
) -> object:
    """Orchestrator wired the way ``build_platform`` wires it.

    ``bootstrap`` always constructs a :class:`FillAttributionLedger`, so the default
    mirrors production.  ``with_ledger=False`` covers a deployment that omits one: slice
    attribution must still happen, which is what the fill-ledger gate used to break.
    """
    orch = _build_orchestrator(
        SimulatedClock(start_ns=1000),
        position_store=positions,
        strategy_positions=slices,
    )
    orch._fill_ledger = (ledger or FillAttributionLedger()) if with_ledger else None
    return orch


def _run_fill(
    order: OrderRequest,
    ack: OrderAck,
    *,
    with_ledger: bool = True,
) -> tuple[MemoryPositionStore, StrategyPositionStore]:
    positions = MemoryPositionStore()
    slices = StrategyPositionStore()
    orch = _orchestrator(positions, slices, with_ledger=with_ledger)
    orch._track_order(order.order_id, order.side, order)  # type: ignore[attr-defined]
    orch._reconcile_fills([ack], correlation_id="tick-cid")  # type: ignore[attr-defined]
    return positions, slices


# ── The seam ─────────────────────────────────────────────────────────────


def test_entry_fill_populates_the_strategy_slice_book() -> None:
    """The regression: an entry fill must reach ``StrategyPositionStore``.

    Without this the Stage-0 deferral ceiling can never bind — the cap reads a
    permanently flat slice and returns at ``position.quantity == 0``.
    """
    order = _entry_order()
    _positions, slices = _run_fill(order, _fill(order))

    slice_pos = slices.get(_SID, _SYMBOL)
    assert slice_pos.quantity == 10, (
        "entry fill did not reach the strategy-slice book — every slice-scoped "
        "reader (Stage-0 deferral cap, exit composer, per-alpha budgets) will "
        "see a flat strategy and never act"
    )


def test_entry_fill_records_opened_at_for_the_slice() -> None:
    """The deferral cap anchors its episode on ``opened_at_ns``.

    ``_on_safety_state_change`` treats ``opened_at_ns() is None`` as "flat, no
    episode to defer" and prunes the anchor, so a missing timestamp silently
    disables the ceiling even when the quantity is right.
    """
    order = _entry_order()
    _positions, slices = _run_fill(order, _fill(order, timestamp_ns=2000))
    assert slices.opened_at_ns(_SID, _SYMBOL) == 2000


def test_single_strategy_attribution_is_exact_against_the_aggregate() -> None:
    """One alpha ⇒ the slice book must equal the aggregate book exactly.

    Guards the self-attribution branch against over- or under-crediting: the
    whole fill and the whole fee belong to the only strategy that traded.
    """
    order = _entry_order()
    positions, slices = _run_fill(order, _fill(order))

    agg = positions.get(_SYMBOL)
    slice_pos = slices.get(_SID, _SYMBOL)
    assert slice_pos.quantity == agg.quantity
    assert slice_pos.cumulative_fees == agg.cumulative_fees


def test_short_entry_fill_is_attributed_signed() -> None:
    """A SELL entry must debit the slice, not credit it."""
    order = _entry_order(order_id="entry-short", side=Side.SELL)
    positions, slices = _run_fill(order, _fill(order))
    assert slices.get(_SID, _SYMBOL).quantity == -10
    assert slices.get(_SID, _SYMBOL).quantity == positions.get(_SYMBOL).quantity


def test_partial_fill_attributes_only_the_filled_quantity() -> None:
    """Attribution follows ``filled_quantity``, not the requested quantity."""
    order = _entry_order(order_id="entry-partial", quantity=10)
    _positions, slices = _run_fill(order, _fill(order, quantity=4))
    assert slices.get(_SID, _SYMBOL).quantity == 4


def test_order_without_a_strategy_id_is_not_self_attributed() -> None:
    """An aggregate/emergency order owns no slice, so it must not credit one."""
    order = _entry_order(order_id="agg-1", strategy_id="")
    _positions, slices = _run_fill(order, _fill(order))
    assert not slices.strategy_ids() or all(
        slices.get(sid, _SYMBOL).quantity == 0 for sid in slices.strategy_ids()
    )


def test_symbol_net_hazard_exit_is_not_self_attributed_to_one_slice() -> None:
    """A symbol-net hazard exit flattens the whole symbol despite carrying a
    ``strategy_id``, so crediting its full fill to that one slice would
    over-debit it when another strategy shares the symbol.

    It must fall through to the proportional split, which distributes across the
    strategies that actually hold quantity.
    """
    positions = MemoryPositionStore()
    slices = StrategyPositionStore()
    # Two strategies each long 10; symbol-net is 20.
    slices.update(_SID, _SYMBOL, 10, Decimal("150.00"), timestamp_ns=500)
    slices.update(_OTHER_SID, _SYMBOL, 10, Decimal("150.00"), timestamp_ns=500)
    positions.update(_SYMBOL, 20, Decimal("150.00"))

    orch = _orchestrator(positions, slices)
    hazard = _entry_order(
        order_id="hz-1",
        side=Side.SELL,
        quantity=20,
        strategy_id=_SID,
        reason=HAZARD_EXIT_REASON_SPIKE,
    )
    orch._track_order(hazard.order_id, hazard.side, hazard)  # type: ignore[attr-defined]
    orch._reconcile_fills([_fill(hazard, quantity=20)], correlation_id="tick-cid")  # type: ignore[attr-defined]

    # Proportional split: both slices unwind, neither is driven through zero.
    assert slices.get(_SID, _SYMBOL).quantity == 0
    assert slices.get(_OTHER_SID, _SYMBOL).quantity == 0, (
        "a symbol-net hazard exit was self-attributed to one slice, leaving the "
        "bystander strategy's slice stale"
    )


# ── The ledger is the live attribution path, not dead weight ─────────────


def test_tracking_an_order_registers_its_attribution_record() -> None:
    """Step 1 of the ledger's contract: ``record()`` on order construction.

    It had no caller at all, so ``allocate_fill`` returned ``[]`` for every
    ``order_id`` and the ledger was inert.
    """
    ledger = FillAttributionLedger()
    orch = _orchestrator(MemoryPositionStore(), StrategyPositionStore(), ledger=ledger)
    order = _entry_order()
    orch._track_order(order.order_id, order.side, order)  # type: ignore[attr-defined]

    allocs = ledger.allocate_fill(order.order_id, 10, Decimal("150.00"))
    assert allocs, "no attribution record was registered for a single-strategy order"
    assert [(sid, signed) for sid, _sym, signed, _px, _fee in allocs] == [(_SID, 10)]


def test_ledger_allocation_signs_a_sell_entry_negative() -> None:
    """Direction comes from ``net_side``; a positive contribution must not flip it."""
    ledger = FillAttributionLedger()
    orch = _orchestrator(MemoryPositionStore(), StrategyPositionStore(), ledger=ledger)
    order = _entry_order(order_id="entry-sell", side=Side.SELL)
    orch._track_order(order.order_id, order.side, order)  # type: ignore[attr-defined]

    allocs = ledger.allocate_fill(order.order_id, 10, Decimal("150.00"))
    assert [signed for _sid, _sym, signed, _px, _fee in allocs] == [-10]


def test_symbol_net_hazard_exit_gets_no_attribution_record() -> None:
    """A symbol-net exit must not be recorded as one slice's whole fill."""
    ledger = FillAttributionLedger()
    orch = _orchestrator(MemoryPositionStore(), StrategyPositionStore(), ledger=ledger)
    hazard = _entry_order(
        order_id="hz-record",
        side=Side.SELL,
        strategy_id=_SID,
        reason=HAZARD_EXIT_REASON_SPIKE,
    )
    orch._track_order(hazard.order_id, hazard.side, hazard)  # type: ignore[attr-defined]
    assert ledger.allocate_fill(hazard.order_id, 10, Decimal("150.00")) == []


def test_order_without_a_strategy_id_gets_no_attribution_record() -> None:
    ledger = FillAttributionLedger()
    orch = _orchestrator(MemoryPositionStore(), StrategyPositionStore(), ledger=ledger)
    order = _entry_order(order_id="agg-record", strategy_id="")
    orch._track_order(order.order_id, order.side, order)  # type: ignore[attr-defined]
    assert ledger.allocate_fill(order.order_id, 10, Decimal("150.00")) == []


def test_partial_fills_through_the_ledger_sum_to_the_total() -> None:
    """Cumulative largest-remainder allocation must not double- or under-count."""
    positions = MemoryPositionStore()
    slices = StrategyPositionStore()
    orch = _orchestrator(positions, slices)
    order = _entry_order(order_id="entry-partials", quantity=10)
    orch._track_order(order.order_id, order.side, order)  # type: ignore[attr-defined]

    orch._reconcile_fills(  # type: ignore[attr-defined]
        [
            OrderAck(
                timestamp_ns=2000,
                correlation_id=order.correlation_id,
                sequence=order.sequence,
                order_id=order.order_id,
                symbol=order.symbol,
                status=OrderAckStatus.PARTIALLY_FILLED,
                filled_quantity=4,
                fill_price=Decimal("150.00"),
                fees=Decimal("0.04"),
            )
        ],
        correlation_id="tick-1",
    )
    assert slices.get(_SID, _SYMBOL).quantity == 4

    orch._reconcile_fills(  # type: ignore[attr-defined]
        [_fill(order, quantity=6, timestamp_ns=3000, fees=Decimal("0.06"))],
        correlation_id="tick-2",
    )
    assert slices.get(_SID, _SYMBOL).quantity == 10
    assert slices.get(_SID, _SYMBOL).quantity == positions.get(_SYMBOL).quantity


# ── The ledger gate no longer decides whether slices are written ─────────


def test_slice_is_attributed_even_without_a_fill_ledger() -> None:
    """Attribution must depend on the slice book, not on the ledger existing.

    The block used to be gated on ``self._fill_ledger is not None``, so a
    deployment that skipped constructing one silently lost slice attribution —
    and with it the Stage-0 ceiling, the composer's scoping, and every per-alpha
    budget.  Neither surviving branch needs the ledger.
    """
    order = _entry_order(order_id="entry-no-ledger")
    _positions, slices = _run_fill(order, _fill(order), with_ledger=False)
    assert slices.get(_SID, _SYMBOL).quantity == 10
