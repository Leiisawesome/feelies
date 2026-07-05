from __future__ import annotations

import re
from decimal import Decimal
from types import SimpleNamespace

import pytest

import feelies.harness.backtest_report as backtest_report_mod
from feelies.core.events import PositionUpdate
from feelies.core.platform_config import PlatformConfig
from feelies.harness.backtest_report import edge_calibration_version, generate_report
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


def _edge_calibration_line(report: str) -> str:
    for line in report.splitlines():
        if "edge_calibration" in line:
            return line
    raise AssertionError("edge_calibration line not found in report")


def _artifact_id(report: str) -> str:
    for line in report.splitlines():
        if "artifact_id" in line:
            match = re.search(r"[0-9a-f]{64}", line)
            assert match is not None, f"no sha256 hex found on artifact_id line: {line!r}"
            return match.group(0)
    raise AssertionError("artifact_id line not found in report")


def _generate_report(*, edge_calibration_factors: dict[str, float] | None = None) -> str:
    return generate_report(
        recorder=_FakeRecorder([]),
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
        edge_calibration_factors=edge_calibration_factors,
    )


def test_edge_calibration_version_none_when_absent() -> None:
    assert edge_calibration_version(None) == "none"
    assert edge_calibration_version({}) == "none"


def test_edge_calibration_version_stable_and_order_independent() -> None:
    a = edge_calibration_version({"sig_a": 0.8, "sig_b": 1.0})
    b = edge_calibration_version({"sig_b": 1.0, "sig_a": 0.8})
    assert a == b
    assert a != "none"


def test_edge_calibration_version_changes_with_factors() -> None:
    assert edge_calibration_version({"sig_a": 0.8}) != edge_calibration_version({"sig_a": 0.9})


def test_generate_report_defaults_edge_calibration_to_none() -> None:
    report = _generate_report()
    assert "none" in _edge_calibration_line(report)


def test_generate_report_artifact_id_changes_with_edge_calibration() -> None:
    """Audit R-1: --edge-calibration is a live trade-path input; two otherwise-identical
    runs that differ only in the calibration factors applied must not collide on
    artifact_id, and the report must state which (if any) calibration was applied."""
    uncalibrated = _generate_report()
    calibrated = _generate_report(edge_calibration_factors={"sig_benign_midcap_v1": 0.75})

    assert "none" in _edge_calibration_line(uncalibrated)
    assert "cal:" in _edge_calibration_line(calibrated)
    assert _artifact_id(uncalibrated) != _artifact_id(calibrated)


def test_code_version_no_git_returns_bare_engine_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(backtest_report_mod, "_git_sha", lambda: None)
    assert backtest_report_mod.code_version() == backtest_report_mod.ENGINE_VERSION


def test_code_version_clean_tree_has_no_dirty_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(backtest_report_mod, "_git_sha", lambda: "abc123def456")
    monkeypatch.setattr(backtest_report_mod, "_working_tree_dirty", lambda: False)
    assert backtest_report_mod.code_version() == "0.1.0+abc123def456"


def test_code_version_dirty_tree_appends_dirty_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Audit P2-6: a locally modified engine must not silently masquerade as
    the last-committed SHA."""
    monkeypatch.setattr(backtest_report_mod, "_git_sha", lambda: "abc123def456")
    monkeypatch.setattr(backtest_report_mod, "_working_tree_dirty", lambda: True)
    assert backtest_report_mod.code_version() == "0.1.0+abc123def456+dirty"


def test_code_version_unknown_dirty_state_omits_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # git present but unavailable/ambiguous (e.g. no git binary on PATH) ->
    # treat like "clean" rather than raising or guessing.
    monkeypatch.setattr(backtest_report_mod, "_git_sha", lambda: "abc123def456")
    monkeypatch.setattr(backtest_report_mod, "_working_tree_dirty", lambda: None)
    assert backtest_report_mod.code_version() == "0.1.0+abc123def456"


def test_working_tree_dirty_returns_bool_or_none_without_raising() -> None:
    assert backtest_report_mod._working_tree_dirty() in (True, False, None)
