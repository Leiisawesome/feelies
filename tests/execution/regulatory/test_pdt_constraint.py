"""Tests for PDT round trips and the $25k minimum-equity gate."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from feelies.core.events import OrderRequest, OrderType, RiskAction, Side
from feelies.execution.regulatory.pdt_constraint import (
    AccountType,
    PDTConfig,
    PDTConstraint,
)
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.risk.basic_risk import BasicRiskEngine, RiskConfig

_NY_TZ = ZoneInfo("America/New_York")


def _ts(year: int, month: int, day: int) -> int:
    """Event-time ns for noon ET on the given date (a stable trading day)."""
    dt = datetime(year, month, day, 12, 0, tzinfo=_NY_TZ)
    return int(dt.timestamp()) * 1_000_000_000


# A Monday, the Friday of that week, and the following Monday.
_MON = _ts(2023, 11, 13)
_FRI = _ts(2023, 11, 17)
_NEXT_MON = _ts(2023, 11, 20)


def _constraint(
    *,
    account_type: AccountType = AccountType.MARGIN_25K,
    min_equity: Decimal = Decimal("25000"),
) -> PDTConstraint:
    return PDTConstraint(
        PDTConfig(
            account_type=account_type,
            account_id="default",
            min_equity=min_equity,
        )
    )


def _round_trip(c: PDTConstraint, ts: int, symbol: str = "AAPL") -> None:
    """Open then fully close a position on the same trading day."""
    c.record_fill("default", symbol, 0, 100, ts)
    c.record_fill("default", symbol, 100, 0, ts)


class TestRoundTripCounting:
    def test_empty(self) -> None:
        c = _constraint()
        assert c.round_trip_count("default", _MON) == 0
        assert not c.is_flagged("default", _MON)

    def test_same_day_open_close_counts_one(self) -> None:
        c = _constraint()
        _round_trip(c, _MON)
        assert c.round_trip_count("default", _MON) == 1

    def test_open_and_close_on_different_days_not_a_day_trade(self) -> None:
        c = _constraint()
        c.record_fill("default", "AAPL", 0, 100, _MON)  # open Monday
        c.record_fill("default", "AAPL", 100, 0, _FRI)  # close Friday
        assert c.round_trip_count("default", _FRI) == 0

    def test_partial_close_same_day_counts(self) -> None:
        c = _constraint()
        c.record_fill("default", "AAPL", 0, 100, _MON)
        c.record_fill("default", "AAPL", 100, 50, _MON)  # partial close
        assert c.round_trip_count("default", _MON) == 1

    def test_adding_to_position_is_not_a_round_trip(self) -> None:
        c = _constraint()
        c.record_fill("default", "AAPL", 0, 100, _MON)
        c.record_fill("default", "AAPL", 100, 200, _MON)  # add, not close
        assert c.round_trip_count("default", _MON) == 0

    def test_same_day_reversal_counts(self) -> None:
        c = _constraint()
        c.record_fill("default", "AAPL", 0, 100, _MON)  # open long
        c.record_fill("default", "AAPL", 100, -100, _MON)  # flip short
        assert c.round_trip_count("default", _MON) == 1


class TestFlag:
    def test_three_round_trips_not_flagged(self) -> None:
        c = _constraint()
        for _ in range(3):
            _round_trip(c, _MON)
        assert c.round_trip_count("default", _MON) == 3
        assert not c.is_flagged("default", _MON)

    def test_four_round_trips_flagged(self) -> None:
        c = _constraint()
        for _ in range(4):
            _round_trip(c, _MON)
        assert c.is_flagged("default", _MON)

    def test_round_trips_outside_window_drop_out(self) -> None:
        c = _constraint()
        for _ in range(4):
            _round_trip(c, _MON)
        # Same week (Friday) the round-trips are still in the 5-day window.
        assert c.is_flagged("default", _FRI)
        # The next Monday is 5 business days on — the Monday trips fall out.
        assert not c.is_flagged("default", _NEXT_MON)


class TestShouldSuppressEntry:
    def test_flagged_and_below_floor_suppresses(self) -> None:
        c = _constraint()
        for _ in range(4):
            _round_trip(c, _MON)
        assert c.should_suppress_entry("default", Decimal("24000"), _MON)

    def test_flagged_but_at_or_above_floor_allows(self) -> None:
        c = _constraint()
        for _ in range(4):
            _round_trip(c, _MON)
        assert not c.should_suppress_entry("default", Decimal("25000"), _MON)

    def test_below_floor_but_not_flagged_allows(self) -> None:
        c = _constraint()
        _round_trip(c, _MON)  # only one round trip
        assert not c.should_suppress_entry("default", Decimal("1000"), _MON)

    def test_non_margin25k_account_never_suppresses(self) -> None:
        c = _constraint(account_type=AccountType.CASH)
        for _ in range(4):
            _round_trip(c, _MON)
        assert not c.should_suppress_entry("default", Decimal("1"), _MON)


def _flagged_constraint() -> PDTConstraint:
    c = _constraint()
    for _ in range(4):
        _round_trip(c, _MON)
    assert c.is_flagged("default", _MON)
    return c


def _order(side: Side, qty: int = 100, symbol: str = "AAPL") -> OrderRequest:
    return OrderRequest(
        timestamp_ns=_MON,
        correlation_id="corr-1",
        sequence=1,
        order_id="ord-1",
        symbol=symbol,
        side=side,
        order_type=OrderType.MARKET,
        quantity=qty,
    )


class TestPDTMinEquityGate:
    """Acceptance: a PDT-flagged account below $25k blocks entries only."""

    def _engine(self, equity: Decimal) -> BasicRiskEngine:
        return BasicRiskEngine(
            RiskConfig(
                max_position_per_symbol=100_000,
                max_gross_exposure_pct=100.0,
                account_equity=equity,
            ),
            pdt_constraint=_flagged_constraint(),
            account_id="default",
        )

    def test_entry_from_flat_suppressed_below_floor(self) -> None:
        engine = self._engine(Decimal("20000"))
        store = MemoryPositionStore()
        verdict = engine.check_order(_order(Side.BUY), store)
        assert verdict.action == RiskAction.REJECT
        assert verdict.reason == "PDT_MIN_EQUITY"

    def test_adding_to_position_suppressed_below_floor(self) -> None:
        engine = self._engine(Decimal("20000"))
        store = MemoryPositionStore()
        store.update("AAPL", 100, Decimal("50"))  # equity stays 20000+0
        verdict = engine.check_order(_order(Side.BUY, qty=50), store)
        assert verdict.action == RiskAction.REJECT
        assert verdict.reason == "PDT_MIN_EQUITY"

    def test_exit_permitted_below_floor(self) -> None:
        engine = self._engine(Decimal("20000"))
        store = MemoryPositionStore()
        store.update("AAPL", 100, Decimal("50"))
        verdict = engine.check_order(_order(Side.SELL, qty=100), store)
        assert verdict.action != RiskAction.REJECT
        assert verdict.reason != "PDT_MIN_EQUITY"

    def test_partial_exit_permitted_below_floor(self) -> None:
        engine = self._engine(Decimal("20000"))
        store = MemoryPositionStore()
        store.update("AAPL", 100, Decimal("50"))
        verdict = engine.check_order(_order(Side.SELL, qty=40), store)
        assert verdict.reason != "PDT_MIN_EQUITY"

    def test_entry_allowed_when_above_floor(self) -> None:
        engine = self._engine(Decimal("30000"))
        store = MemoryPositionStore()
        verdict = engine.check_order(_order(Side.BUY), store)
        assert verdict.action == RiskAction.ALLOW

    def test_entry_allowed_when_not_flagged(self) -> None:
        engine = BasicRiskEngine(
            RiskConfig(
                max_position_per_symbol=100_000,
                max_gross_exposure_pct=100.0,
                account_equity=Decimal("20000"),
            ),
            pdt_constraint=_constraint(),  # zero round trips → not flagged
            account_id="default",
        )
        store = MemoryPositionStore()
        verdict = engine.check_order(_order(Side.BUY), store)
        assert verdict.action == RiskAction.ALLOW

    def test_no_constraint_is_inert(self) -> None:
        engine = BasicRiskEngine(
            RiskConfig(
                max_position_per_symbol=100_000,
                max_gross_exposure_pct=100.0,
                account_equity=Decimal("20000"),
            ),
        )
        store = MemoryPositionStore()
        verdict = engine.check_order(_order(Side.BUY), store)
        assert verdict.action == RiskAction.ALLOW

    def test_record_fill_forwards_to_constraint(self) -> None:
        engine = self._engine(Decimal("30000"))
        # An ENTRY that flips a fresh long is recorded; the gate stays
        # quiet here because equity is above the floor.
        engine.record_fill("MSFT", 0, 100, _MON)
        engine.record_fill("MSFT", 100, 0, _MON)
        # No assertion on internal state beyond no-raise; the constraint
        # unit tests cover counting semantics.
