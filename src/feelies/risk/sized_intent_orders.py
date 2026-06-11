"""Shared Layer-3 ``SizedPositionIntent`` -> per-leg ``OrderRequest`` logic.

Both :class:`feelies.risk.basic_risk.BasicRiskEngine` and the per-alpha
:class:`feelies.alpha.risk_wrapper.AlphaBudgetRiskWrapper` translate a
portfolio intent into per-leg orders with identical semantics; this module
holds the single canonical implementation so the two paths cannot drift.

Determinism (Inv-5): symbols are processed in lexicographic order, share
counts use ``Decimal`` arithmetic with ``ROUND_HALF_UP`` (never float), and
``order_id`` is derived deterministically from the intent provenance, so two
replays of the same intent emit a bit-identical order tuple.
"""

from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable

from feelies.core.events import (
    OrderRequest,
    OrderType,
    RiskAction,
    RiskVerdict,
    Side,
    SizedPositionIntent,
)
from feelies.core.identifiers import derive_order_id
from feelies.portfolio.position_store import PositionStore
from feelies.risk.sized_intent_result import SizedIntentRiskResult

_logger = logging.getLogger(__name__)

CheckOrder = Callable[[OrderRequest, PositionStore], RiskVerdict]
DroppedLegsCallback = Callable[[SizedPositionIntent, list[tuple[str, str]]], None]


def resolve_mark(symbol: str, current: object, positions: PositionStore) -> Decimal:
    """Return the best-available mark for translating USD -> shares.

    Prefers the latest live mark when recorded; otherwise falls back to the
    position's ``avg_entry_price`` for the boot-time case before any quote has
    flowed through.  Returns ``0`` when neither is available -- the caller must
    treat zero as "skip this leg" (Inv-11 fail-safe).
    """
    latest = getattr(positions, "latest_mark", None)
    if callable(latest):
        try:
            m = latest(symbol)
            if isinstance(m, Decimal) and m > 0:
                return m
        except Exception as exc:  # pragma: no cover - defensive
            # Inv-11 fail-safe: fall back to cost basis rather than raising
            # into the risk path.  The swallow itself is a degraded mode
            # (live-mark feed bug), so surface it via WARNING for the
            # promotion-window slippage forensics.
            _logger.warning(
                "resolve_mark(%s): latest_mark accessor raised %s; "
                "falling back to avg_entry_price",
                symbol,
                exc,
            )
    avg = getattr(current, "avg_entry_price", Decimal("0"))
    if isinstance(avg, Decimal) and avg > 0:
        return avg
    return Decimal("0")


def build_sized_intent_orders(
    intent: SizedPositionIntent,
    positions: PositionStore,
    *,
    check_order: CheckOrder,
    on_dropped_legs: DroppedLegsCallback | None = None,
) -> SizedIntentRiskResult:
    """Translate a ``SizedPositionIntent`` into vetted per-leg orders.

    ``check_order`` is invoked per leg so the caller controls which risk
    surface enforces limits (the wrapper routes through its per-alpha budget
    gate; the base engine routes through itself).  A ``FORCE_FLATTEN`` verdict
    aborts the whole intent and requests global escalation; ``REJECT`` drops
    only the offending leg; ``SCALE_DOWN`` rebuilds the leg at the scaled
    quantity.  Veto-dropped legs are surfaced via ``on_dropped_legs``.
    """
    if not intent.target_positions:
        return SizedIntentRiskResult(orders=())

    orders: list[OrderRequest] = []
    dropped: list[tuple[str, str]] = []
    for symbol in sorted(intent.target_positions):
        tgt = intent.target_positions[symbol]
        current = positions.get(symbol)
        mark = resolve_mark(symbol, current, positions)
        if mark <= 0:
            continue

        target_shares = int(
            (Decimal(str(tgt.target_usd)) / mark).to_integral_value(
                rounding=ROUND_HALF_UP,
            )
        )
        delta_shares = target_shares - current.quantity
        if delta_shares == 0:
            continue

        side = Side.BUY if delta_shares > 0 else Side.SELL
        quantity = abs(delta_shares)

        order_id = derive_order_id(f"{intent.correlation_id}:{intent.sequence}:{symbol}")
        disclosed_cost = intent.disclosed_cost_total_bps_by_symbol.get(symbol, 0.0)
        order = OrderRequest(
            timestamp_ns=intent.timestamp_ns,
            correlation_id=intent.correlation_id,
            sequence=intent.sequence,
            source_layer="PORTFOLIO",
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            strategy_id=intent.strategy_id,
            reason="PORTFOLIO",
            g12_disclosed_cost_total_bps=disclosed_cost,
        )

        verdict = check_order(order, positions)
        if verdict.action == RiskAction.FORCE_FLATTEN:
            return SizedIntentRiskResult(
                orders=(),
                requires_global_risk_escalation=True,
            )
        if verdict.action == RiskAction.REJECT:
            dropped.append((symbol, verdict.reason))
            continue
        if verdict.action == RiskAction.SCALE_DOWN:
            scaled_qty = max(
                1,
                int(
                    (Decimal(quantity) * Decimal(str(verdict.scaling_factor))).to_integral_value(
                        rounding=ROUND_HALF_UP
                    ),
                ),
            )
            if scaled_qty != quantity:
                order = OrderRequest(
                    timestamp_ns=intent.timestamp_ns,
                    correlation_id=intent.correlation_id,
                    sequence=intent.sequence,
                    source_layer="PORTFOLIO",
                    order_id=order_id,
                    symbol=symbol,
                    side=side,
                    order_type=OrderType.MARKET,
                    quantity=scaled_qty,
                    strategy_id=intent.strategy_id,
                    reason="PORTFOLIO",
                    g12_disclosed_cost_total_bps=disclosed_cost,
                )
        orders.append(order)

    if dropped and on_dropped_legs is not None:
        on_dropped_legs(intent, dropped)

    return SizedIntentRiskResult(orders=tuple(orders))
