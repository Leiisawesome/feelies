"""Corporate-action ex-date calendar and replay guard."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from feelies.core.events import NBBOQuote
from feelies.storage.memory_event_log import InMemoryEventLog
from feelies.storage.reference.corporate_actions import (
    CorporateActionKind,
    ExDateCalendar,
    ExDateEntry,
    check_ex_date_replay_window,
    find_ex_date_violations,
    load_ex_date_calendar,
    replay_calendar_date_span,
)
from feelies.storage.reference.paths import EX_DATE_CALENDAR_PATH


def _quote(exchange_ts_ns: int, symbol: str = "AAPL") -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=exchange_ts_ns,
        correlation_id=f"{symbol}:{exchange_ts_ns}:0",
        sequence=0,
        symbol=symbol,
        bid=Decimal("100"),
        ask=Decimal("100.05"),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=exchange_ts_ns,
    )


def test_load_bundled_calendar() -> None:
    cal = load_ex_date_calendar(EX_DATE_CALENDAR_PATH)
    assert isinstance(cal, ExDateCalendar)


def test_find_violation_inside_span() -> None:
    entry = ExDateEntry(
        symbol="AAPL",
        ex_date=date(2026, 1, 15),
        kind=CorporateActionKind.SPLIT,
    )
    cal = ExDateCalendar(entries=(entry,))
    violations = find_ex_date_violations(
        frozenset({"AAPL"}),
        date(2026, 1, 14),
        date(2026, 1, 16),
        cal,
    )
    assert len(violations) == 1
    assert violations[0].ex_date == date(2026, 1, 15)


def test_no_violation_outside_span() -> None:
    entry = ExDateEntry(
        symbol="AAPL",
        ex_date=date(2026, 6, 1),
        kind=CorporateActionKind.DIVIDEND,
    )
    cal = ExDateCalendar(entries=(entry,))
    violations = find_ex_date_violations(
        frozenset({"AAPL"}),
        date(2026, 1, 14),
        date(2026, 1, 16),
        cal,
    )
    assert violations == ()


def test_check_replay_window_from_event_log(tmp_path: Path) -> None:
    cal_path = tmp_path / "ex_dates.yaml"
    cal_path.write_text(
        "schema_version: '1.0'\n"
        "entries:\n"
        "  - symbol: AAPL\n"
        "    ex_date: 2026-01-15\n"
        "    kind: SPLIT\n",
    )
    cal = load_ex_date_calendar(cal_path)
    log = InMemoryEventLog()
    # 2026-01-15 session anchor from fixtures (ET via exchange ts)
    t0 = 1_768_532_400_000_000_000
    log.append(_quote(t0))
    log.append(_quote(t0 + 60_000_000_000))
    span = replay_calendar_date_span(log)
    assert span is not None
    violations = check_ex_date_replay_window(
        frozenset({"AAPL"}),
        log,
        cal,
    )
    assert len(violations) == 1


def test_duplicate_entry_rejected(tmp_path: Path) -> None:
    cal_path = tmp_path / "dup.yaml"
    cal_path.write_text(
        "schema_version: '1.0'\nentries:\n"
        "  - {symbol: AAPL, ex_date: 2026-01-15, kind: SPLIT}\n"
        "  - {symbol: AAPL, ex_date: 2026-01-15, kind: SPLIT}\n",
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_ex_date_calendar(cal_path)
