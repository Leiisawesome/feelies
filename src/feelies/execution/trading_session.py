"""RTH session calendar + entry-fill gating for backtest (BT-16).

Models US equity regular-hours bounds (09:30–16:00 ET), full-day market
holidays, and early-close half-days (13:00 ET close).  Entry fills are
suppressed outside RTH and on holidays; exits are always permitted
(Inv-11 fail-safe).

MOC cutoff shifting on half-days is owned by
:mod:`feelies.execution.moc_session` (BT-8); this module shares the
``early_close_dates`` surface on :class:`~feelies.core.platform_config.PlatformConfig`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from feelies.core.events import OrderRequest, Side
from feelies.execution.moc_session import (
    et_clock_to_ns,
    session_date_from_calendar_path,
    session_date_from_ns,
)

_NS_PER_SECOND = 1_000_000_000

# Stable reject token for routers and the risk engine.
RTH_ENTRY_SUPPRESSED = "RTH_ENTRY_SUPPRESSED"
MARKET_HOLIDAY = "MARKET_HOLIDAY"


@dataclass(frozen=True, kw_only=True)
class TradingSessionBounds:
    """Per-session RTH open/close anchors in exchange-time nanoseconds."""

    session_date: date
    rth_open_ns: int
    rth_close_ns: int
    is_holiday: bool = False
    is_early_close: bool = False
    no_entry_first_seconds: int = 0

    def covers_ns(self, ts_ns: int) -> bool:
        """Whether ``ts_ns`` falls on ``session_date`` in America/New_York."""
        return session_date_from_ns(ts_ns) == self.session_date

    def no_entry_before_ns(self) -> int:
        """First exchange-time instant when new entries are allowed."""
        return self.rth_open_ns + self.no_entry_first_seconds * _NS_PER_SECOND

    def is_within_rth(self, ts_ns: int) -> bool:
        """Continuous-session window (open inclusive, close exclusive)."""
        if self.is_holiday or not self.covers_ns(ts_ns):
            return False
        return self.rth_open_ns <= ts_ns < self.rth_close_ns


def resolve_trading_session_bounds(
    session_date: date,
    *,
    rth_open_et: str = "09:30",
    rth_close_et: str = "16:00",
    early_close: bool = False,
    early_close_rth_close_et: str = "13:00",
    is_holiday: bool = False,
    no_entry_first_seconds: int = 0,
) -> TradingSessionBounds:
    """Build RTH bounds for a single calendar session date."""
    close_et = early_close_rth_close_et if early_close else rth_close_et
    return TradingSessionBounds(
        session_date=session_date,
        rth_open_ns=et_clock_to_ns(session_date, rth_open_et),
        rth_close_ns=et_clock_to_ns(session_date, close_et),
        is_holiday=is_holiday,
        is_early_close=early_close,
        no_entry_first_seconds=no_entry_first_seconds,
    )


def should_suppress_entry(
    exchange_ts_ns: int,
    bounds: TradingSessionBounds,
    opens_or_increases: bool,
) -> tuple[bool, str]:
    """Whether an opening/increasing fill must be refused at ``exchange_ts_ns``.

    Returns ``(True, reason_token)`` when suppressed, else ``(False, "")``.
    Exits and reductions always return ``(False, "")``.
    """
    if not opens_or_increases:
        return False, ""
    if not bounds.covers_ns(exchange_ts_ns):
        return True, RTH_ENTRY_SUPPRESSED
    if bounds.is_holiday:
        return True, MARKET_HOLIDAY
    if exchange_ts_ns < bounds.no_entry_before_ns():
        return True, RTH_ENTRY_SUPPRESSED
    if exchange_ts_ns >= bounds.rth_close_ns:
        return True, RTH_ENTRY_SUPPRESSED
    return False, ""



def opens_or_increases_signed(current_qty: int, post_signed: int) -> bool:
    """Entry detection: True iff the resulting position grows or flips sign.

    Single source of truth for ENTRY classification across the BT-4 PDT
    min-equity gate, the BT-15 Reg-T buying-power gate, and the BT-16
    RTH router-side suppression — a future edge-case fix lands here.
    """
    return (
        abs(post_signed) > abs(current_qty)
        or (
            current_qty != 0
            and post_signed != 0
            and (current_qty > 0) != (post_signed > 0)
        )
    )


def order_opens_or_increases(
    current_qty: int,
    side: Side,
    quantity: int,
) -> bool:
    """Whether applying ``(side, quantity)`` opens or increases exposure."""
    signed = quantity if side is Side.BUY else -quantity
    return opens_or_increases_signed(current_qty, current_qty + signed)


@dataclass
class RthEntryFillGate:
    """Router-side ENTRY suppression using optional live position qty."""

    bounds: TradingSessionBounds | None
    _position_qty: Callable[[str], int] | None = field(
        default=None, repr=False,
    )

    def bind_position_qty(self, fn: Callable[[str], int]) -> None:
        self._position_qty = fn

    def should_suppress(
        self,
        request: OrderRequest,
        exchange_ts_ns: int,
    ) -> tuple[bool, str]:
        if self.bounds is None:
            return False, ""
        current_qty = 0
        if self._position_qty is not None:
            current_qty = self._position_qty(request.symbol)
        if not order_opens_or_increases(
            current_qty, request.side, request.quantity,
        ):
            return False, ""
        return should_suppress_entry(
            exchange_ts_ns, self.bounds, opens_or_increases=True,
        )



def build_trading_session_from_platform(
    *,
    rth_session_gating_enabled: bool,
    rth_session_date: str | None,
    event_calendar_path: str | None,
    rth_open_et: str,
    rth_close_et: str,
    early_close_dates: tuple[str, ...],
    early_close_rth_close_et: str,
    market_holiday_dates: tuple[str, ...],
    no_entry_first_seconds: int,
) -> TradingSessionBounds | None:
    """Resolve bounds when RTH gating is enabled.

    Returns ``None`` when gating is disabled or no session date can be
    determined (inert — no entry suppression).
    """
    if not rth_session_gating_enabled:
        return None
    raw_date = rth_session_date
    if raw_date is None:
        cal_date = session_date_from_calendar_path(
            Path(event_calendar_path) if event_calendar_path else None,
        )
        if cal_date is not None:
            raw_date = cal_date.isoformat()
    if raw_date is None:
        return None
    session_date = date.fromisoformat(raw_date)
    holiday = session_date.isoformat() in frozenset(market_holiday_dates)
    early = session_date.isoformat() in frozenset(early_close_dates)
    return resolve_trading_session_bounds(
        session_date,
        rth_open_et=rth_open_et,
        rth_close_et=rth_close_et,
        early_close=early,
        early_close_rth_close_et=early_close_rth_close_et,
        is_holiday=holiday,
        no_entry_first_seconds=no_entry_first_seconds,
    )


__all__ = [
    "MARKET_HOLIDAY",
    "RTH_ENTRY_SUPPRESSED",
    "RthEntryFillGate",
    "TradingSessionBounds",
    "build_trading_session_from_platform",
    "resolve_trading_session_bounds",
    "order_opens_or_increases",
    "opens_or_increases_signed",
    "should_suppress_entry",
]
