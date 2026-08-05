"""Turn a Layer-3 ``SizedPositionIntent`` target into a candidate order leg.

Execution Decision owns *how* an approved target becomes something submittable:
resolving the mark that converts USD to shares, deriving the delta against the
current position, choosing a side, minting the order, and re-rounding it when
risk scales it down.  Risk owns *whether* a leg is admitted.

Those two were interleaved in one loop in ``risk/sized_intent_orders.py``, and
they have to stay interleaved — each leg's admission depends on the exposure the
previously admitted legs already committed, so the caps bind cumulatively rather
than every leg seeing the same pre-intent snapshot.  Splitting the *loop* would
break that.  Splitting the *responsibilities* does not: risk still drives, and
calls in here for construction.

Determinism (Inv-5): share counts use ``Decimal`` with ``ROUND_HALF_UP`` (never
float), and ``order_id`` derives from the intent's own provenance, so two replays
of one intent mint a bit-identical leg.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from feelies.core.events import (
    OrderRequest,
    OrderType,
    Side,
    SizedPositionIntent,
)
from feelies.core.identifiers import derive_order_id
from feelies.portfolio.position_store import PositionStore

_logger = logging.getLogger(__name__)


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


@dataclass(frozen=True, kw_only=True)
class PlannedLeg:
    """One symbol's candidate order, plus what risk needs to price its exposure."""

    order: OrderRequest
    mark: Decimal
    #: Position quantity before this leg, so the caller can compute the exposure
    #: delta an admitted leg commits without re-reading the store.
    current_quantity: int

    @property
    def signed_quantity(self) -> int:
        q = self.order.quantity
        return q if self.order.side is Side.BUY else -q


def plan_leg(
    intent: SizedPositionIntent,
    symbol: str,
    positions: PositionStore,
) -> PlannedLeg | None:
    """Build the candidate order for one symbol, or ``None`` to skip it.

    ``None`` when no usable mark exists (nothing can be priced) or the target
    already matches the current position (nothing to trade).
    """
    target = intent.target_positions[symbol]
    current = positions.get(symbol)
    mark = resolve_mark(symbol, current, positions)
    if mark <= 0:
        return None

    target_shares = int(
        (Decimal(str(target.target_usd)) / mark).to_integral_value(rounding=ROUND_HALF_UP)
    )
    delta_shares = target_shares - current.quantity
    if delta_shares == 0:
        return None

    return PlannedLeg(
        order=_mint(
            intent,
            symbol,
            side=Side.BUY if delta_shares > 0 else Side.SELL,
            quantity=abs(delta_shares),
        ),
        mark=mark,
        current_quantity=current.quantity,
    )


def rescale_leg(leg: PlannedLeg, scaling_factor: float) -> PlannedLeg | None:
    """Re-mint *leg* at a scaled quantity, or ``None`` if it rounds away.

    A leg that scales to zero is dropped rather than floored to one share —
    forcing a one-share order would trade purely to satisfy the rounding.
    """
    scaled = int(
        (Decimal(leg.order.quantity) * Decimal(str(scaling_factor))).to_integral_value(
            rounding=ROUND_HALF_UP
        )
    )
    if scaled <= 0:
        return None
    if scaled == leg.order.quantity:
        return leg
    return PlannedLeg(
        order=_mint(
            leg.order,
            leg.order.symbol,
            side=leg.order.side,
            quantity=scaled,
        ),
        mark=leg.mark,
        current_quantity=leg.current_quantity,
    )


def _mint(
    provenance: SizedPositionIntent | OrderRequest,
    symbol: str,
    *,
    side: Side,
    quantity: int,
) -> OrderRequest:
    """Mint a PORTFOLIO leg carrying the intent's provenance.

    ``order_id`` is derived from ``correlation_id``/``sequence``/``symbol``, so a
    rescale re-mints the *same* id — the leg is one decision whose size changed,
    not a second order.
    """
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


__all__ = ["PlannedLeg", "plan_leg", "rescale_leg", "resolve_mark"]
