"""Static per-symbol borrow tiers for backtest short entries.

Lightweight locate model: a symbol is ``available`` (easy to borrow — no HTB
fee), ``hard`` (HTB fee path when ``cost_htb_borrow_annual_bps > 0``), or
``unavailable`` (short entries refused with ``LOCATE_UNAVAILABLE``).  Symbols
omitted from the table default to ``available`` (conservative for large-cap
universes).  No intraday rate-spike or dynamic locate modeling.
"""

from __future__ import annotations

from feelies.core.borrow_availability import BorrowTier as BorrowTier
from feelies.core.borrow_availability import build_borrow_table as build_borrow_table
from feelies.core.borrow_availability import parse_borrow_tier as parse_borrow_tier
from feelies.execution.intent import OrderIntent


def is_short_sale_intent(intent: OrderIntent) -> bool:
    """True when the order would open or increase SHORT exposure.

    Only short *sales* are subject to Reg-SHO / locate constraints.  Buys,
    covers, partial covers and long-side exits are never short sales.

    Delegates to the platform's single admission basis
    (:func:`~feelies.execution.order_admission.exposure_delta_from_intent`) so
    this and the order gates can never disagree about what a short sale is.
    An earlier standalone implementation keyed on the ``TradingIntent`` arm and
    called a zero-target ``REVERSE_LONG_TO_SHORT`` a short sale even though it
    trades to flat.
    """
    from feelies.execution.order_admission import exposure_delta_from_intent

    return exposure_delta_from_intent(intent).opens_or_increases_short


def htb_fee_applies(tier: BorrowTier, short_sale: bool) -> bool:
    """True when the fill should carry ``OrderRequest.is_short`` for HTB fees."""
    return short_sale and tier == BorrowTier.HARD
