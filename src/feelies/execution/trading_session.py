"""RTH calendar and entry-fill gating for backtests.

Models US equity regular-hours bounds (09:30–16:00 ET), full-day market
holidays, and early-close half-days (13:00 ET close).  Entry fills are
suppressed outside RTH and on holidays; exits are always permitted
(Inv-11 fail-safe).

MOC cutoff shifting on half-days is owned by
:mod:`feelies.execution.moc_session`; this module shares the
``early_close_dates`` surface on :class:`~feelies.core.platform_config.PlatformConfig`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from feelies.core.events import OrderRequest, Side
from feelies.core.trading_session import TradingSessionBounds as TradingSessionBounds
from feelies.core.trading_session import et_clock_to_ns
from feelies.core.trading_session import (
    in_session_flatten_window as in_session_flatten_window,
)
from feelies.core.trading_session import (
    session_flatten_deadline_ns as session_flatten_deadline_ns,
)
from feelies.execution.moc_session import session_date_from_calendar_path

# Stable reject token for routers and the risk engine.
RTH_ENTRY_SUPPRESSED = "RTH_ENTRY_SUPPRESSED"
MARKET_HOLIDAY = "MARKET_HOLIDAY"


def resolve_trading_session_bounds(
    session_date: date,
    *,
    rth_open_et: str = "09:30",
    rth_close_et: str = "16:00",
    early_close: bool = False,
    early_close_rth_close_et: str = "13:00",
    is_holiday: bool = False,
    no_entry_first_seconds: int = 0,
    early_close_dates: tuple[str, ...] = (),
    market_holiday_dates: tuple[str, ...] = (),
) -> TradingSessionBounds:
    """Build RTH bounds for a single calendar session date."""
    early_close_date_set = frozenset(early_close_dates)
    market_holiday_date_set = frozenset(market_holiday_dates)
    session_key = session_date.isoformat()
    effective_early_close = early_close or session_key in early_close_date_set
    effective_holiday = is_holiday or session_key in market_holiday_date_set
    close_et = early_close_rth_close_et if effective_early_close else rth_close_et
    return TradingSessionBounds(
        session_date=session_date,
        rth_open_ns=et_clock_to_ns(session_date, rth_open_et),
        rth_close_ns=et_clock_to_ns(session_date, close_et),
        is_holiday=effective_holiday,
        is_early_close=effective_early_close,
        no_entry_first_seconds=no_entry_first_seconds,
        rth_open_et=rth_open_et,
        rth_close_et=rth_close_et,
        early_close_rth_close_et=early_close_rth_close_et,
        market_holiday_dates=market_holiday_date_set,
        early_close_dates=early_close_date_set,
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
    effective = bounds.resolve_for_timestamp(exchange_ts_ns)
    if not effective.covers_ns(exchange_ts_ns):
        return True, RTH_ENTRY_SUPPRESSED
    if effective.is_holiday:
        return True, MARKET_HOLIDAY
    if exchange_ts_ns < effective.no_entry_before_ns():
        return True, RTH_ENTRY_SUPPRESSED
    if exchange_ts_ns >= effective.rth_close_ns:
        return True, RTH_ENTRY_SUPPRESSED
    return False, ""


def opens_or_increases_signed(current_qty: int, post_signed: int) -> bool:
    """Entry detection: True iff the resulting position grows or flips sign.

    This is the shared entry classifier for PDT equity, Reg-T buying power,
    and RTH router gates.
    """
    return abs(post_signed) > abs(current_qty) or (
        current_qty != 0 and post_signed != 0 and (current_qty > 0) != (post_signed > 0)
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
        default=None,
        repr=False,
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
            current_qty,
            request.side,
            request.quantity,
        ):
            return False, ""
        return should_suppress_entry(
            exchange_ts_ns,
            self.bounds,
            opens_or_increases=True,
        )

    def reset(self) -> None:
        """Position callback is process wiring; nothing run-scoped to restore."""
        return


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
        early_close_dates=early_close_dates,
        market_holiday_dates=market_holiday_dates,
    )


__all__ = [
    "MARKET_HOLIDAY",
    "RTH_ENTRY_SUPPRESSED",
    "RthEntryFillGate",
    "TradingSessionBounds",
    "build_trading_session_from_platform",
    "in_session_flatten_window",
    "resolve_trading_session_bounds",
    "order_opens_or_increases",
    "opens_or_increases_signed",
    "session_flatten_deadline_ns",
    "should_suppress_entry",
]
