"""Prior-session regime calibration quotes. Pure given the loader."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from feelies.core.events import NBBOQuote, Trade
from feelies.harness.regime_calibration import prior_session_calibration_quotes

_TZ = ZoneInfo("America/New_York")


def _ns(day: int, hour: int, minute: int) -> int:
    return int(datetime(2026, 3, day, hour, minute, tzinfo=_TZ).timestamp() * 1e9)


def _quote(day: int, hour: int, minute: int, seq: int) -> NBBOQuote:
    ts = _ns(day, hour, minute)
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"q:{seq}",
        sequence=seq,
        symbol="APP",
        exchange_timestamp_ns=ts,
        bid=Decimal("100.00"),
        ask=Decimal("100.10"),
        bid_size=100,
        ask_size=100,
    )


def _trade(day: int, hour: int, minute: int, seq: int) -> Trade:
    ts = _ns(day, hour, minute)
    return Trade(
        timestamp_ns=ts,
        correlation_id=f"t:{seq}",
        sequence=seq,
        symbol="APP",
        exchange_timestamp_ns=ts,
        price=Decimal("100.05"),
        size=10,
        conditions=(),
    )


def test_prior_date_is_the_previous_weekday_and_keeps_rth_order() -> None:
    seen: dict[str, object] = {}

    def loader(symbols: tuple[str, ...] | list[str], day: str):
        seen["symbols"] = tuple(symbols)
        seen["day"] = day
        return (
            _quote(25, 10, 0, 1),
            _quote(25, 8, 0, 2),
            _trade(25, 10, 1, 3),
            _quote(25, 10, 2, 4),
        )

    quotes, provenance = prior_session_calibration_quotes(
        symbols=("ZZZ", "APP"),
        session_date="2026-03-26",
        max_quotes=10,
        loader=loader,
    )
    assert seen["day"] == "2026-03-25"
    assert seen["symbols"] == ("ZZZ", "APP")
    assert [quote.sequence for quote in quotes] == [1, 4]
    assert provenance == ("2026-03-25", 2)


def test_monday_selects_the_previous_friday() -> None:
    seen: dict[str, object] = {}

    def loader(symbols: tuple[str, ...] | list[str], day: str):
        del symbols
        seen["day"] = day
        return (_quote(27, 10, 0, 1),)

    quotes, provenance = prior_session_calibration_quotes(
        symbols=("APP",),
        session_date="2026-03-30",
        max_quotes=10,
        loader=loader,
    )
    assert seen["day"] == "2026-03-27"
    assert [quote.sequence for quote in quotes] == [1]
    assert provenance == ("2026-03-27", 1)


def test_missing_prior_session_is_empty() -> None:
    def loader(symbols: tuple[str, ...] | list[str], day: str):
        del symbols, day
        return None

    quotes, provenance = prior_session_calibration_quotes(
        symbols=("APP",),
        session_date="2026-03-26",
        max_quotes=10,
        loader=loader,
    )
    assert quotes == ()
    assert provenance == (None, 0)


def test_cap_keeps_the_first_rth_quotes_in_loader_order() -> None:
    events = (
        _quote(25, 9, 30, 1),
        _quote(25, 8, 0, 2),
        _quote(25, 9, 31, 3),
        _quote(25, 9, 32, 4),
        _quote(25, 9, 33, 5),
    )

    def loader(symbols: tuple[str, ...] | list[str], day: str):
        del symbols, day
        return events

    quotes, provenance = prior_session_calibration_quotes(
        symbols=("APP",),
        session_date="2026-03-26",
        max_quotes=3,
        loader=loader,
    )
    assert [quote.sequence for quote in quotes] == [1, 3, 4]
    assert provenance == ("2026-03-25", 3)
