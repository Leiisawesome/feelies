from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from feelies.core.events import PositionUpdate
from feelies.core.platform_config import PlatformConfig
from feelies.harness.backtest_report import generate_report
from feelies.ingestion.massive_ingestor import IngestResult


class _FakeRecorder:
    def __init__(self, position_updates: list[PositionUpdate]) -> None:
        self._position_updates = position_updates

    def of_type(self, event_type):
        if event_type is PositionUpdate:
            return list(self._position_updates)
        return []


class _FakeTradeJournal:
    def query(self):
        return []


class _FakePositionStore:
    def __init__(self, position) -> None:
        self._position = position

    def all_positions(self):
        return {"AAPL": self._position}


class _FakeOrchestrator:
    def __init__(self) -> None:
        self.account_equity = Decimal("1000")
        self.position_store = _FakePositionStore(
            SimpleNamespace(
                realized_pnl=Decimal("500"),
                unrealized_pnl=Decimal("500"),
                cumulative_fees=Decimal("0"),
                quantity=100,
            )
        )
        self.trade_journal = _FakeTradeJournal()
        self.kill_switch = None
        self.metric_collector = None
        self.alpha_registry = None


def test_generate_report_uses_live_nav_for_max_exposure_pct() -> None:
    report = generate_report(
        recorder=_FakeRecorder(
            [
                PositionUpdate(
                    timestamp_ns=1,
                    correlation_id="cid-1",
                    sequence=1,
                    symbol="AAPL",
                    quantity=100,
                    avg_price=Decimal("100"),
                    realized_pnl=Decimal("500"),
                    unrealized_pnl=Decimal("500"),
                    cumulative_fees=Decimal("0"),
                )
            ]
        ),
        ingest_result=IngestResult(
            events_ingested=0,
            pages_processed=0,
            symbols_with_gaps=0,
            duplicates_filtered=0,
            symbols_completed=frozenset(),
        ),
        config=PlatformConfig(version="test", symbols=frozenset({"AAPL"})),
        orchestrator=_FakeOrchestrator(),
        symbol_str="AAPL",
        date_range="2026-01-01",
    )

    assert "Max exposure" in report
    assert "500.00%" in report
    assert "1000.00%" not in report


def test_generate_report_uses_unrealized_pnl_for_drawdown() -> None:
    report = generate_report(
        recorder=_FakeRecorder(
            [
                PositionUpdate(
                    timestamp_ns=1,
                    correlation_id="cid-1",
                    sequence=1,
                    symbol="AAPL",
                    quantity=100,
                    avg_price=Decimal("100"),
                    realized_pnl=Decimal("0"),
                    unrealized_pnl=Decimal("-200"),
                    cumulative_fees=Decimal("0"),
                )
            ]
        ),
        ingest_result=IngestResult(
            events_ingested=0,
            pages_processed=0,
            symbols_with_gaps=0,
            duplicates_filtered=0,
            symbols_completed=frozenset(),
        ),
        config=PlatformConfig(version="test", symbols=frozenset({"AAPL"})),
        orchestrator=_FakeOrchestrator(),
        symbol_str="AAPL",
        date_range="2026-01-01",
    )

    assert "Max drawdown" in report
    assert "-$200.00 (-20.00%)" in report
