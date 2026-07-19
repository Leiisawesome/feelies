"""BT-18 acceptance: raw L1 policy + ex-date replay integrity guard."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path


from feelies.core.events import NBBOQuote
from feelies.storage.memory_event_log import InMemoryEventLog
from feelies.storage.reference.corporate_actions import (
    RAW_UNADJUSTED_L1_POLICY,
    check_ex_date_replay_window,
    load_ex_date_calendar,
)
from tests.fixtures.event_logs._generate import SESSION_OPEN_NS


def _quote(exchange_ts_ns: int) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=exchange_ts_ns,
        correlation_id=f"AAPL:{exchange_ts_ns}:0",
        sequence=0,
        symbol="AAPL",
        bid=Decimal("150"),
        ask=Decimal("150.05"),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=exchange_ts_ns,
    )


def test_raw_unadjusted_policy_documented() -> None:
    assert "unadjusted" in RAW_UNADJUSTED_L1_POLICY.lower()
    doc = Path(__file__).resolve().parents[2] / "docs" / "data_adjustment_policy.md"
    assert doc.is_file()
    assert "ex-date" in doc.read_text(encoding="utf-8").lower()


def test_replay_spanning_ex_date_produces_violation(tmp_path: Path) -> None:
    cal_path = tmp_path / "ex_dates.yaml"
    cal_path.write_text(
        "schema_version: '1.0'\nentries:\n"
        "  - symbol: AAPL\n"
        "    ex_date: 2026-01-15\n"
        "    kind: DIVIDEND\n",
    )
    cal = load_ex_date_calendar(cal_path)
    log = InMemoryEventLog()
    log.append(_quote(SESSION_OPEN_NS))
    log.append(_quote(SESSION_OPEN_NS + 120_000_000_000))

    violations = check_ex_date_replay_window(
        frozenset({"AAPL"}),
        log,
        cal,
    )
    assert len(violations) == 1
    assert violations[0].ex_date == date(2026, 1, 15)
    assert "2026-01-15" in violations[0].message()


def test_empty_calendar_produces_no_violations(tmp_path: Path) -> None:
    cal_path = tmp_path / "empty.yaml"
    cal_path.write_text("schema_version: '1.0'\nentries: []\n")
    cal = load_ex_date_calendar(cal_path)
    log = InMemoryEventLog()
    log.append(_quote(SESSION_OPEN_NS))
    assert check_ex_date_replay_window(frozenset({"AAPL"}), log, cal) == ()
