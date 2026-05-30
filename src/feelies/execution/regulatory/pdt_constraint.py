"""Pattern Day Trader (PDT) tracking + $25k minimum-equity maintenance (BT-4).

The locked account type for this platform is ``margin_25k`` — a margin
account that *opens* above the $25,000 threshold and is therefore
PDT-*exempt*: the FINRA 3-round-trip / 5-business-day hard cap is **not**
modeled, and there is no cash-account T+2 settlement branch.

Two pieces live here:

1. A rolling 5-business-day **round-trip counter** keyed by ``account_id``.
   A round-trip (a "day trade") is recorded whenever a fill closes — in
   whole or in part — a position that was *opened the same trading day*.
   Four or more round-trips inside the rolling window sets the PDT
   **flag**.  The flag is forensic: it never suppresses a fill on its own.

2. The one real backtest constraint at this tier: a PDT-flagged account
   whose live equity has dropped **below $25,000** is restricted from
   opening new day trades until equity is restored.  The risk engine
   consults :meth:`PDTConstraint.should_suppress_entry` on every ENTRY
   order; exits are always permitted (Inv-11, fail-safe).

Determinism (Inv-5)
-------------------
Every method is a pure function of the fills observed and the event-time
nanosecond timestamps carried on those fills.  The trading day is derived
from the timestamp via ``ZoneInfo("America/New_York")`` (the same ET
clock the event calendar uses); no wall clock and no RNG are consulted,
so replay is bit-identical.

Extensibility
-------------
``AccountType`` carries ``MARGIN_UNDER_25K`` and ``CASH`` members so the
config grammar is forward-compatible, but only the ``MARGIN_25K`` path is
implemented now (:meth:`should_suppress_entry` is a no-op for the others;
``bootstrap`` refuses to construct the constraint for an unimplemented
account type).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from zoneinfo import ZoneInfo

_NY_TZ = ZoneInfo("America/New_York")
_NS_PER_SECOND = 1_000_000_000

# Round-trip dates older than this many calendar days from the most
# recent observation can never fall inside a 5-business-day window, so
# they are pruned to bound the per-account list across a long backtest.
_PRUNE_AGE_CALENDAR_DAYS = 14


class AccountType(str, Enum):
    """Locked-extensible account-type taxonomy (BT-4).

    Only :attr:`MARGIN_25K` is implemented; the other members exist so
    the ``platform.account_type`` grammar accepts them without rework.
    """

    MARGIN_25K = "margin_25k"
    MARGIN_UNDER_25K = "margin_under_25k"
    CASH = "cash"


@dataclass(frozen=True, kw_only=True)
class PDTConfig:
    """Configuration for :class:`PDTConstraint`."""

    account_type: AccountType = AccountType.MARGIN_25K
    account_id: str = "default"
    min_equity: Decimal = Decimal("25000")
    # PDT flag fires at 4+ round-trips inside the rolling window.
    flag_round_trip_threshold: int = 4
    window_business_days: int = 5


class PDTConstraint:
    """Rolling round-trip counter + minimum-equity entry gate.

    State is per ``account_id``; the platform feeds a single configured
    account id, but the dict-keyed shape honours the multi-account
    contract in the remediation plan.
    """

    def __init__(self, config: PDTConfig) -> None:
        self._config = config
        # Trading date on which the current open position was established,
        # keyed by (account_id, symbol).  Absent ⇒ flat.
        self._open_trade_date: dict[tuple[str, str], date] = {}
        # One entry per recorded round-trip: the trading date it closed.
        self._round_trips: dict[str, list[date]] = {}

    @property
    def config(self) -> PDTConfig:
        return self._config

    # ── Fill observation ─────────────────────────────────────────────

    def record_fill(
        self,
        account_id: str,
        symbol: str,
        prev_qty: int,
        new_qty: int,
        timestamp_ns: int,
    ) -> None:
        """Update round-trip state from a single applied fill.

        ``prev_qty`` / ``new_qty`` are the *signed* position quantities
        before and after the fill.  A round-trip is recorded when the
        fill reduces (partially or fully closes, or reverses) a position
        that was opened earlier the **same** trading day.
        """
        day = self._trading_date(timestamp_ns)
        key = (account_id, symbol)
        opened_day = self._open_trade_date.get(key)

        closed_today = False
        if prev_qty == 0:
            # Fresh open from flat.
            if new_qty != 0:
                self._open_trade_date[key] = day
        elif new_qty == 0:
            # Full close.
            if opened_day == day:
                closed_today = True
            self._open_trade_date.pop(key, None)
        elif (prev_qty > 0) != (new_qty > 0):
            # Sign flip: the old side closed, a new side opened today.
            if opened_day == day:
                closed_today = True
            self._open_trade_date[key] = day
        elif abs(new_qty) < abs(prev_qty):
            # Partial close, same side — position stays open, open date
            # unchanged.
            if opened_day == day:
                closed_today = True
        else:
            # Add to the same side: opened date is the earliest open.
            self._open_trade_date.setdefault(key, day)

        if closed_today:
            self._round_trips.setdefault(account_id, []).append(day)
            self._prune(account_id, day)

    # ── Queries ──────────────────────────────────────────────────────

    def round_trip_count(self, account_id: str, now_ns: int) -> int:
        """Round-trips inside the rolling business-day window ending now."""
        today = self._trading_date(now_ns)
        window = self._config.window_business_days
        trips = self._round_trips.get(account_id, ())
        return sum(
            1
            for d in trips
            if 0 <= _business_days_between(d, today) < window
        )

    def is_flagged(self, account_id: str, now_ns: int) -> bool:
        """True once 4+ round-trips land inside the rolling window."""
        return (
            self.round_trip_count(account_id, now_ns)
            >= self._config.flag_round_trip_threshold
        )

    def should_suppress_entry(
        self,
        account_id: str,
        current_equity: Decimal,
        now_ns: int,
    ) -> bool:
        """Whether a new ENTRY (opening) fill must be refused.

        Only the ``MARGIN_25K`` path is implemented: a PDT-flagged account
        below the $25k maintenance floor is barred from opening new day
        trades.  Returns ``False`` for the other (unimplemented) account
        types so the gate is inert if one is ever wired without code.
        """
        if self._config.account_type is not AccountType.MARGIN_25K:
            return False
        if current_equity >= self._config.min_equity:
            return False
        return self.is_flagged(account_id, now_ns)

    # ── Internals ────────────────────────────────────────────────────

    def _prune(self, account_id: str, today: date) -> None:
        trips = self._round_trips.get(account_id)
        if not trips:
            return
        self._round_trips[account_id] = [
            d for d in trips
            if (today - d).days <= _PRUNE_AGE_CALENDAR_DAYS
        ]

    @staticmethod
    def _trading_date(timestamp_ns: int) -> date:
        return datetime.fromtimestamp(
            timestamp_ns // _NS_PER_SECOND, tz=_NY_TZ,
        ).date()


def _business_days_between(d_from: date, d_to: date) -> int:
    """Count weekdays in the half-open interval ``(d_from, d_to]``.

    ``d_from == d_to`` yields ``0``.  Holidays are *not* subtracted — a
    deliberate simplification: this counter only sets a forensic flag, so
    an exact market calendar is unwarranted, and ignoring holidays errs
    toward dropping a round-trip slightly early (a conservative,
    fewer-false-flags bias).
    """
    if d_to <= d_from:
        return 0
    total_days = (d_to - d_from).days
    full_weeks, remainder = divmod(total_days, 7)
    count = full_weeks * 5
    start_weekday = d_from.weekday()  # Monday == 0 … Sunday == 6
    for offset in range(1, remainder + 1):
        if (start_weekday + offset) % 7 < 5:
            count += 1
    return count
