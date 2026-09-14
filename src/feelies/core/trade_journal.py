"""TradeRecord — frozen dataclass for a completed trade lifecycle.

Lives in core so kernel can construct it without importing storage.
The TradeJournal Protocol stays in storage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from feelies.core.events import Side, TrendMechanism


@dataclass(frozen=True, kw_only=True)
class TradeRecord:
    """Complete lifecycle record for a single trade.

    Captures the full decision chain from signal through fill,
    with computed execution quality fields.

    ``realized_pnl`` is **per-trade differential** — the PnL realized
    by this specific fill only.  Computed as the change in the
    position's cumulative realized PnL across this fill.  Contrast
    with ``PositionUpdate.realized_pnl``, which is cumulative.
    """

    order_id: str
    symbol: str
    strategy_id: str
    side: Side
    requested_quantity: int
    filled_quantity: int
    fill_price: Decimal | None
    signal_timestamp_ns: int
    submit_timestamp_ns: int
    fill_timestamp_ns: int | None
    cost_bps: Decimal
    fees: Decimal
    realized_pnl: Decimal
    correlation_id: str
    trading_intent: str = ""  # TradingIntent.name at order submission time
    # Capture mechanism and fill-time regime so attribution needs no live lookup.
    trend_mechanism: TrendMechanism | None = None
    expected_half_life_seconds: int = 0
    regime_state: str = ""
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def net_pnl(self) -> Decimal:
        """Realized PnL net of explicit fees.

        Under the platform cost convention, a taker fill
        executes at the crossed price (BUY lifts the ask, SELL hits the bid),
        so ``realized_pnl`` already INCLUDES the half-spread paid to cross — it
        is not mid-to-mid, and ``fees`` carries no separate ``spread_cost``.
        ``fees`` holds explicit charges only (commission, regulatory/TAF,
        and any forced-exit panic slippage).  ``realized_pnl - fees`` therefore
        nets those explicit charges off a PnL that already reflects the spread;
        consumers must not subtract a spread component a second time.
        """
        return self.realized_pnl - self.fees
