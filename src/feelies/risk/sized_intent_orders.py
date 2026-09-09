"""Admit or veto the legs of a Layer-3 ``SizedPositionIntent``.

Both :class:`feelies.risk.basic_risk.BasicRiskEngine` and the per-alpha
:class:`feelies.alpha.risk_wrapper.AlphaBudgetRiskWrapper` decompose a portfolio
intent with identical semantics; this module holds the single canonical
implementation so the two paths cannot drift.

Risk owns *whether* each leg is admitted and what exposure an admitted leg
commits.  Constructing the leg — resolving the mark, converting USD to shares,
choosing a side, minting the order, re-rounding a scale-down — is Execution
Decision work and lives in
:mod:`feelies.execution.sized_intent_legs`.

The loop stays interleaved on purpose: a leg's admission depends on the exposure
previously admitted legs already committed (``additional_exposure``), so the caps
bind cumulatively rather than every leg seeing the same pre-intent snapshot.
Separating the responsibilities does not require separating the loop.

Determinism (Inv-5): symbols are processed in lexicographic order.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
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
from feelies.core.position import PositionStore
from feelies.risk.sized_intent_result import SizedIntentRiskResult

_logger = logging.getLogger(__name__)

# Concrete engines accept additional_exposure; simple test doubles may ignore it.
CheckOrder = Callable[..., RiskVerdict]
DroppedLegsCallback = Callable[[SizedPositionIntent, list[tuple[str, str]]], None]


def _resolve_mark(symbol: str, current: object, positions: PositionStore) -> Decimal:
    """Return the best-available mark for translating USD -> shares."""
    latest = getattr(positions, "latest_mark", None)
    if callable(latest):
        try:
            m = latest(symbol)
            if isinstance(m, Decimal) and m > 0:
                return m
        except Exception as exc:  # pragma: no cover - defensive
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


@dataclass(frozen=True, kw_only=True)
class _PlannedLeg:
    """One symbol's candidate order, plus what risk needs to price its exposure."""

    order: OrderRequest
    mark: Decimal
    current_quantity: int

    @property
    def signed_quantity(self) -> int:
        q = self.order.quantity
        return q if self.order.side is Side.BUY else -q


def _mint(
    provenance: SizedPositionIntent | OrderRequest,
    symbol: str,
    *,
    side: Side,
    quantity: int,
) -> OrderRequest:
    """Mint a PORTFOLIO leg carrying the intent's provenance."""
    disclosed = (
        provenance.disclosed_cost_total_bps_by_symbol.get(symbol, 0.0)
        if isinstance(provenance, SizedPositionIntent)
        else provenance.g12_disclosed_cost_total_bps
    )
    return OrderRequest(
        timestamp_ns=provenance.timestamp_ns,
        correlation_id=provenance.correlation_id,
        sequence=provenance.sequence,
        source_layer="PORTFOLIO",
        order_id=derive_order_id(f"{provenance.correlation_id}:{provenance.sequence}:{symbol}"),
        symbol=symbol,
        side=side,
        order_type=OrderType.MARKET,
        quantity=quantity,
        strategy_id=provenance.strategy_id,
        reason="PORTFOLIO",
        g12_disclosed_cost_total_bps=disclosed,
    )


def _plan_leg(
    intent: SizedPositionIntent,
    symbol: str,
    positions: PositionStore,
) -> _PlannedLeg | None:
    """Build the candidate order for one symbol, or ``None`` to skip it."""
    target = intent.target_positions[symbol]
    current = positions.get(symbol)
    mark = _resolve_mark(symbol, current, positions)
    if mark <= 0:
        return None

    target_shares = int(
        (Decimal(str(target.target_usd)) / mark).to_integral_value(rounding=ROUND_HALF_UP)
    )
    delta_shares = target_shares - current.quantity
    if delta_shares == 0:
        return None

    return _PlannedLeg(
        order=_mint(
            intent,
            symbol,
            side=Side.BUY if delta_shares > 0 else Side.SELL,
            quantity=abs(delta_shares),
        ),
        mark=mark,
        current_quantity=current.quantity,
    )


def _rescale_leg(leg: _PlannedLeg, scaling_factor: float) -> _PlannedLeg | None:
    """Re-mint *leg* at a scaled quantity, or ``None`` if it rounds away."""
    scaled = int(
        (Decimal(leg.order.quantity) * Decimal(str(scaling_factor))).to_integral_value(
            rounding=ROUND_HALF_UP
        )
    )
    if scaled <= 0:
        return None
    if scaled == leg.order.quantity:
        return leg
    return _PlannedLeg(
        order=_mint(
            leg.order,
            leg.order.symbol,
            side=leg.order.side,
            quantity=scaled,
        ),
        mark=leg.mark,
        current_quantity=leg.current_quantity,
    )


def build_sized_intent_orders(
    intent: SizedPositionIntent,
    positions: PositionStore,
    *,
    check_order: CheckOrder,
    on_dropped_legs: DroppedLegsCallback | None = None,
) -> SizedIntentRiskResult:
    """Translate a sized intent into independently risk-checked orders.

    Admitted exposure accumulates across legs so the intent cannot exceed a
    cap collectively. Force-flatten aborts the intent; rejection, zero scaling,
    and raised risk checks drop only the offending leg.
    """
    if not intent.target_positions:
        return SizedIntentRiskResult(orders=())

    orders: list[OrderRequest] = []
    dropped: list[tuple[str, str]] = []
    running_extra = Decimal("0")
    for symbol in sorted(intent.target_positions):
        leg = _plan_leg(intent, symbol, positions)
        if leg is None:
            continue

        try:
            verdict = check_order(leg.order, positions, additional_exposure=running_extra)
        except Exception as exc:  # noqa: BLE001 — Inv-11: never raise from the risk path
            _logger.warning(
                "build_sized_intent_orders: check_order raised for leg %s "
                "(strategy_id=%s, correlation_id=%s): %r — veto-dropping the leg",
                symbol,
                intent.strategy_id,
                intent.correlation_id,
                exc,
            )
            dropped.append((symbol, f"check_order raised: {exc!r}"))
            continue
        if verdict.action == RiskAction.FORCE_FLATTEN:
            return SizedIntentRiskResult(
                orders=(),
                requires_global_risk_escalation=True,
            )
        if verdict.action == RiskAction.REJECT:
            dropped.append((symbol, verdict.reason))
            continue
        if verdict.action == RiskAction.SCALE_DOWN:
            scaled = _rescale_leg(leg, verdict.scaling_factor)
            if scaled is None:
                dropped.append((symbol, f"scaled down to zero quantity: {verdict.reason}"))
                continue
            leg = scaled

        # Include each admitted leg in later legs' exposure checks.
        post_qty = leg.current_quantity + leg.signed_quantity
        running_extra += (abs(post_qty) - abs(leg.current_quantity)) * leg.mark
        orders.append(leg.order)

    if dropped and on_dropped_legs is not None:
        on_dropped_legs(intent, dropped)

    return SizedIntentRiskResult(orders=tuple(orders))
