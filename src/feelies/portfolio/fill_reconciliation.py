"""Engine-7 fill accounting: slice ownership, journal legs, fill reconciliation."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from feelies.core.events import (
    AlertSeverity,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    PositionUpdate,
    Side,
)
from feelies.kernel.fill_bindings import (
    TradeRecord,
    _regime_label_for,
    observe_kill_switch,
)
from feelies.kernel.forced_exit_reasons import (
    _RISK_FORCED_EXIT_REASONS,
    _SELF_ATTRIBUTED_FORCED_EXIT_REASONS,
)
from feelies.portfolio.fill_attribution import largest_remainder_split, split_fees

logger = logging.getLogger(__name__)


def _order_owns_one_slice(order: OrderRequest) -> bool:
    """Return whether every fill belongs to the order strategy slice."""
    if not order.strategy_id:
        return False
    if order.reason in _SELF_ATTRIBUTED_FORCED_EXIT_REASONS:
        return True
    return order.reason not in _RISK_FORCED_EXIT_REASONS


@dataclass(frozen=True, kw_only=True)
class _TradeJournalLeg:
    """One trade-journal row's share of a single fill."""

    strategy_id: str
    filled_quantity: int
    fees: Decimal
    realized_pnl: Decimal
    metadata: dict[str, str]


def _trade_journal_legs(
    order: OrderRequest,
    *,
    filled_quantity: int,
    fees: Decimal,
    realized_pnl: Decimal,
    attributed_legs: Sequence[tuple[str, int, Decimal, Decimal]],
    announced_quantity: int | None = None,
) -> list[_TradeJournalLeg]:
    """Build per-strategy journal rows for one fill.

    Slice-owned orders keep one owner; symbol-net exits use attributed slice economics. Missing attribution falls back to one aggregate row."""
    base_metadata = {
        "order_reason": order.reason,
        "order_source_layer": order.source_layer,
    }
    if announced_quantity is not None:
        # Present only when the kernel clamped this exit, so its presence is
        # itself the signal that submitted size != announced size.
        base_metadata["forced_exit_announced_quantity"] = str(announced_quantity)
    if not attributed_legs:
        return [
            _TradeJournalLeg(
                strategy_id=order.strategy_id,
                filled_quantity=filled_quantity,
                fees=fees,
                realized_pnl=realized_pnl,
                metadata=base_metadata,
            )
        ]

    # Preserve each slice's realized PnL instead of blending aggregate basis.
    owns_one_slice = _order_owns_one_slice(order)
    metadata = (
        base_metadata
        if owns_one_slice
        else {**base_metadata, "forced_exit_strategy_id": order.strategy_id}
    )
    return [
        _TradeJournalLeg(
            strategy_id=strategy_id,
            filled_quantity=abs(qty),
            fees=leg_fees,
            realized_pnl=leg_realized,
            metadata=dict(metadata),
        )
        for strategy_id, qty, leg_fees, leg_realized in attributed_legs
    ]


def _record_fill_attribution(
    self: Any,
    order_id: str,
    side: Side,
    order: OrderRequest,
) -> None:
    """Record deterministic strategy allocations for an order.

    Single-slice orders self-attribute; symbol-net exits allocate across live slices."""
    if self._fill_ledger is None or not _order_owns_one_slice(order):
        return
    from feelies.portfolio.fill_attribution import AlphaContribution, AttributionRecord

    self._fill_ledger.record(
        AttributionRecord(
            order_id=order_id,
            symbol=order.symbol,
            net_side=side,
            net_quantity=order.quantity,
            contributions=(
                AlphaContribution(
                    strategy_id=order.strategy_id,
                    signed_quantity=order.quantity,
                    proportion=1.0,
                ),
            ),
        )
    )


def _distribute_fill_to_strategies(
    self: Any,
    symbol: str,
    signed_qty: int,
    fill_price: Decimal,
    fees: Decimal,
    timestamp_ns: int,
) -> list[tuple[str, int, Decimal, Decimal]]:
    """Distribute a fill proportionally across per-alpha strategy positions.

    Used when no fill-attribution record exists (emergency flatten,
    stop exit, or attribution failure).  Distributes ``signed_qty``
    proportionally to each strategy's current quantity for this
    symbol, keeping global and strategy position stores in sync.

    Uses largest-remainder rounding so the sum of per-alpha deltas
    equals ``signed_qty`` exactly.

    Returns the ``(strategy_id, signed_quantity, fees, realized_delta)`` legs it
    applied — ``realized_delta`` measured around each slice's own update, so the
    caller can journal a symbol-net forced exit against the slices it actually
    closed instead of the synthetic order's ``strategy_id`` (Inv-13).  Empty when
    no slice book is wired or no strategy holds the symbol.
    """
    if self._strategy_positions is None:
        return []

    # Inv-5: iterate strategies in a deterministic (sorted) order.
    # ``strategy_ids()`` returns a ``frozenset``; materialising it directly
    # would make the largest-remainder tie-break and per-alpha fee split
    # depend on hash-iteration order (process/seed dependent).
    strategy_ids = sorted(self._strategy_positions.strategy_ids())
    if not strategy_ids:
        return []

    # Reducing fills allocate only across slices on the closable side.
    strategy_qtys: list[tuple[str, int]] = []
    for sid in strategy_ids:
        q = self._strategy_positions.get(sid, symbol).quantity
        if q * signed_qty < 0:
            strategy_qtys.append((sid, q))
    if not strategy_qtys:
        # Increasing fills fall back across holders; warn only on store drift.
        strategy_qtys = [
            (sid, q)
            for sid in strategy_ids
            if (q := self._strategy_positions.get(sid, symbol).quantity) != 0
        ]
        if strategy_qtys:
            slice_book_net = sum(q for _sid, q in strategy_qtys)
            symbol_net = self._positions.get(symbol).quantity
            if slice_book_net + signed_qty != symbol_net:
                logger.warning(
                    "Fill attribution for %s: the slice book and the symbol-net "
                    "store have diverged (slices sum to %d, symbol-net %d after a "
                    "%d-share fill); falling back to a split across all %d holders.",
                    symbol,
                    slice_book_net,
                    symbol_net,
                    signed_qty,
                    len(strategy_qtys),
                )
    if not strategy_qtys:
        return []

    # Same rounding and fee convention the ledger uses, so a fill rounds
    # identically whichever path attributes it.
    abs_fill = abs(signed_qty)
    alloc_qtys = largest_remainder_split(abs_fill, [abs(q) for _sid, q in strategy_qtys])
    alloc_fees = split_fees(fees, alloc_qtys)

    applied: list[tuple[str, int, Decimal, Decimal]] = []
    alloc_sign = 1 if signed_qty > 0 else -1
    for (sid, _q), alloc_qty, alloc_fee in zip(
        strategy_qtys, alloc_qtys, alloc_fees, strict=True
    ):
        if alloc_qty == 0:
            continue
        prev_slice = self._strategy_positions.get(sid, symbol).realized_pnl
        slice_position = self._strategy_positions.update(
            sid,
            symbol,
            alloc_sign * alloc_qty,
            fill_price,
            fees=alloc_fee,
            timestamp_ns=timestamp_ns,
        )
        applied.append(
            (
                sid,
                alloc_sign * alloc_qty,
                alloc_fee,
                slice_position.realized_pnl - prev_slice,
            )
        )

    return applied


def _reconcile_fills(
    self: Any,
    acks: list[OrderAck],
    correlation_id: str,
) -> None:
    """Update positions from fill acknowledgements.

    Determines sign of quantity_delta from the original order's
    Side: BUY adds to position, SELL subtracts.
    Writes TradeRecords to the trade journal for post-trade forensics.

    Inv-11 fail-safe: fills for unknown order IDs are rejected
    (not applied) and surfaced via alert.  Defaulting to BUY
    would risk increasing exposure from an untracked sell order.

    Position mutations require ``status ∈ {FILLED, PARTIALLY_FILLED}``
    with positive ``filled_quantity`` and a non-null ``fill_price``.
    """
    for ack in acks:
        # Debit cancel or expiry fees even without a fill.
        if (
            ack.status
            in (
                OrderAckStatus.CANCELLED,
                OrderAckStatus.EXPIRED,
            )
            and ack.fees
            and ack.fees > 0
        ):
            self._positions.debit_fees(ack.symbol, ack.fees)
            if self._strategy_positions is not None and ack.order_id in self._active_orders:
                strategy_id = self._active_orders[ack.order_id][2].strategy_id
                if strategy_id:
                    self._strategy_positions.debit_fees(
                        strategy_id,
                        ack.symbol,
                        ack.fees,
                    )
            fee_position = self._positions.get(ack.symbol)
            self._bus.publish(
                PositionUpdate(
                    timestamp_ns=ack.timestamp_ns,
                    correlation_id=correlation_id,
                    sequence=self._seq.next(),
                    symbol=ack.symbol,
                    quantity=fee_position.quantity,
                    avg_price=fee_position.avg_entry_price,
                    realized_pnl=fee_position.realized_pnl,
                    unrealized_pnl=fee_position.unrealized_pnl,
                    cumulative_fees=fee_position.cumulative_fees,
                    cost_bps=ack.cost_bps,
                )
            )

        if ack.status in (
            OrderAckStatus.FILLED,
            OrderAckStatus.PARTIALLY_FILLED,
        ):
            if ack.fill_price is None or ack.filled_quantity <= 0:
                self._publish_alert(
                    timestamp_ns=self._clock.now_ns(),
                    correlation_id=correlation_id,
                    severity=AlertSeverity.WARNING,
                    alert_name="fill_ack_missing_price_or_quantity",
                    message=f"{ack.status.name} ack missing economics (order_id={ack.order_id!r}, symbol={ack.symbol!r}, filled_quantity={ack.filled_quantity}, fill_price={ack.fill_price!r}).",
                    context={
                        "order_id": ack.order_id,
                        "symbol": ack.symbol,
                        "status": ack.status.name,
                        "filled_quantity": ack.filled_quantity,
                        "fill_price": str(ack.fill_price),
                    },
                )
                continue
        else:
            fill_like = ack.fill_price is not None and ack.filled_quantity > 0
            if fill_like:
                self._publish_alert(
                    timestamp_ns=self._clock.now_ns(),
                    correlation_id=correlation_id,
                    severity=AlertSeverity.WARNING,
                    alert_name="fill_payload_inconsistent_with_ack_status",
                    message=f"Ignoring fill-like payload on {ack.status.name} ack (order_id={ack.order_id!r}, symbol={ack.symbol!r}).",
                    context={
                        "order_id": ack.order_id,
                        "symbol": ack.symbol,
                        "status": ack.status.name,
                        "filled_quantity": ack.filled_quantity,
                        "fill_price": str(ack.fill_price),
                    },
                )
            continue

        if ack.order_id not in self._active_orders:
            self._publish_alert(
                timestamp_ns=self._clock.now_ns(),
                correlation_id=correlation_id,
                severity=AlertSeverity.WARNING,
                alert_name="fill_for_unknown_order",
                message=f"Fill for unknown order_id={ack.order_id}, symbol={ack.symbol}, qty={ack.filled_quantity}, price={ack.fill_price}. Rejected: cannot determine side (Inv-11 fail-safe).",
                context={
                    "order_id": ack.order_id,
                    "symbol": ack.symbol,
                    "filled_quantity": ack.filled_quantity,
                    "fill_price": str(ack.fill_price),
                },
            )
            continue

        _, side, order = self._active_orders[ack.order_id]
        signed_qty = ack.filled_quantity
        if side == Side.SELL:
            signed_qty = -signed_qty

        # Track fills so a working-exit fallback submits only the residual.
        if ack.order_id in self._working_exit_fallback:
            self._order_filled_qty[ack.order_id] = (
                self._order_filled_qty.get(ack.order_id, 0) + ack.filled_quantity
            )

        prev_position = self._positions.get(ack.symbol)
        prev_realized = prev_position.realized_pnl
        prev_qty = prev_position.quantity
        position = self._positions.update(
            ack.symbol,
            signed_qty,
            ack.fill_price,
            fees=ack.fees,
            timestamp_ns=ack.timestamp_ns,
        )
        # Mirror the fill into the observational FIFO lot ledger.
        self._lot_ledger.apply_fill(
            ack.symbol,
            signed_qty,
            ack.fill_price,
            timestamp_ns=ack.timestamp_ns,
            strategy_id=order.strategy_id,
            intent=self._order_trading_intent.get(ack.order_id, ""),
        )

        # Feed the PDT counter when the risk engine supports it.
        record_fill = getattr(self._risk_engine, "record_fill", None)
        if callable(record_fill):
            record_fill(
                ack.symbol,
                prev_qty,
                position.quantity,
                ack.timestamp_ns,
            )

        # Record per-slice fees and realized PnL for journal attribution.
        attributed_legs: list[tuple[str, int, Decimal, Decimal]] = []
        if self._strategy_positions is not None:
            alpha_allocs: list[tuple[str, str, int, Decimal, Decimal]] = []
            if self._fill_ledger is not None:
                try:
                    alpha_allocs = self._fill_ledger.allocate_fill(
                        ack.order_id,
                        ack.filled_quantity,
                        ack.fill_price,
                        total_fees=ack.fees,
                        is_final=ack.status == OrderAckStatus.FILLED,
                    )
                except Exception:
                    logger.exception(
                        "Fill attribution failed for order %s — "
                        "falling back to proportional distribution",
                        ack.order_id,
                    )
                    alpha_allocs = []

            if alpha_allocs:
                for strat_id, sym, alpha_signed, price, alloc_fees in alpha_allocs:
                    prev_slice = self._strategy_positions.get(strat_id, sym).realized_pnl
                    slice_position = self._strategy_positions.update(
                        strat_id,
                        sym,
                        alpha_signed,
                        price,
                        fees=alloc_fees,
                        timestamp_ns=ack.timestamp_ns,
                    )
                    attributed_legs.append(
                        (
                            strat_id,
                            alpha_signed,
                            alloc_fees,
                            slice_position.realized_pnl - prev_slice,
                        )
                    )
            elif _order_owns_one_slice(order):
                # Missing ledger data still self-attributes single-slice orders.
                prev_slice = self._strategy_positions.get(
                    order.strategy_id, ack.symbol
                ).realized_pnl
                slice_position = self._strategy_positions.update(
                    order.strategy_id,
                    ack.symbol,
                    signed_qty,
                    ack.fill_price,
                    fees=ack.fees,
                    timestamp_ns=ack.timestamp_ns,
                )
                attributed_legs = [
                    (
                        order.strategy_id,
                        signed_qty,
                        ack.fees,
                        slice_position.realized_pnl - prev_slice,
                    )
                ]
            else:
                # Without attribution, split proportionally to keep stores in
                # sync. Aggregate PnL stays exact; per-alpha PnL is estimated.
                attributed_legs = _distribute_fill_to_strategies(
                    self,
                    ack.symbol,
                    signed_qty,
                    ack.fill_price,
                    ack.fees,
                    ack.timestamp_ns,
                )
        self._bus.publish(
            PositionUpdate(
                timestamp_ns=ack.timestamp_ns,
                correlation_id=correlation_id,
                sequence=self._seq.next(),
                symbol=ack.symbol,
                quantity=position.quantity,
                avg_price=position.avg_entry_price,
                realized_pnl=position.realized_pnl,
                unrealized_pnl=position.unrealized_pnl,
                cumulative_fees=position.cumulative_fees,
                cost_bps=ack.cost_bps,
            )
        )

        disclosed = order.g12_disclosed_cost_total_bps
        alert_ratio = self._realized_cost_alert_ratio
        if disclosed > 0:
            breached = float(ack.cost_bps) > disclosed * alert_ratio
            if not breached:
                # A fill within the disclosed band breaks the streak.
                self._realized_cost_breach_streak.pop(order.strategy_id, None)
            else:
                streak = self._realized_cost_breach_streak.get(order.strategy_id, 0) + 1
                self._realized_cost_breach_streak[order.strategy_id] = streak
                # Repeated cost overruns can trigger the kill switch.
                escalate = (
                    self._realized_cost_escalation_enabled
                    and streak >= self._realized_cost_escalation_streak
                )
                severity = AlertSeverity.CRITICAL if escalate else AlertSeverity.WARNING
                self._publish_alert(
                    timestamp_ns=self._clock.now_ns(),
                    correlation_id=correlation_id,
                    severity=severity,
                    alert_name="g12_realized_cost_exceeds_disclosure",
                    message=f"Fill cost_bps={float(ack.cost_bps):.4f} exceeds {alert_ratio}× G12 disclosed one-way cost_total_bps={disclosed:.4f} (strategy_id={order.strategy_id!r}, symbol={ack.symbol!r}, order_id={ack.order_id!r}, streak={streak})",
                    context={
                        "strategy_id": order.strategy_id,
                        "symbol": ack.symbol,
                        "order_id": ack.order_id,
                        "realized_cost_bps": float(ack.cost_bps),
                        "g12_disclosed_cost_total_bps": disclosed,
                        "alert_ratio": alert_ratio,
                        "breach_streak": streak,
                        "escalated": escalate,
                    },
                )
                if (
                    escalate
                    and self._kill_switch is not None
                    and not observe_kill_switch(self._kill_switch.is_active)
                ):
                    self._kill_switch.activate(
                        reason="realized_cost_persistent_overrun",
                        activated_by="orchestrator",
                    )

        if self._trade_journal is not None:
            for leg in _trade_journal_legs(
                order,
                filled_quantity=ack.filled_quantity,
                fees=ack.fees,
                realized_pnl=position.realized_pnl - prev_realized,
                attributed_legs=attributed_legs,
                announced_quantity=self._forced_exit_announced_quantity.get(ack.order_id),
            ):
                _trade_mech, _trade_hl = self._last_signal_mechanism.get(
                    (leg.strategy_id, ack.symbol),
                    (None, 0),
                )
                self._trade_journal.record(
                    TradeRecord(
                        order_id=ack.order_id,
                        symbol=ack.symbol,
                        strategy_id=leg.strategy_id,
                        side=side,
                        requested_quantity=order.quantity,
                        filled_quantity=leg.filled_quantity,
                        fill_price=ack.fill_price,
                        signal_timestamp_ns=order.timestamp_ns,
                        submit_timestamp_ns=order.timestamp_ns,
                        fill_timestamp_ns=ack.timestamp_ns,
                        cost_bps=ack.cost_bps,
                        fees=leg.fees,
                        realized_pnl=leg.realized_pnl,
                        correlation_id=order.correlation_id,
                        trading_intent=self._order_trading_intent.get(
                            ack.order_id,
                            "",
                        ),
                        trend_mechanism=_trade_mech,
                        expected_half_life_seconds=_trade_hl,
                        regime_state=_regime_label_for(self, ack.symbol),
                        # Preserve forced-exit class and producing layer on the
                        # trade; ``forced_exit_strategy_id`` keeps the synthetic
                        # author recoverable now that ``strategy_id`` names the
                        # slice the exit closed (Inv-13).
                        metadata=leg.metadata,
                    )
                )
        if order.strategy_id:
            self._alpha_symbols_with_fills.add((order.strategy_id, ack.symbol))

    self._prune_terminal_orders()
