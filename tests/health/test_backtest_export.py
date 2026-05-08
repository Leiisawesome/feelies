from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

from feelies.core.events import OrderAck, OrderAckStatus, Signal, SignalDirection
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.health.backtest_export import export_backtest_health_dir


def test_export_backtest_health_dir_minimal(tmp_path: Path) -> None:
    out = tmp_path / "run1"
    sig = Signal(
        timestamp_ns=1_700_000_000_000_000_000,
        correlation_id="cid-1",
        sequence=1,
        symbol="AAA",
        strategy_id="test_alpha",
        direction=SignalDirection.LONG,
        strength=0.25,
        edge_estimate_bps=1.5,
        horizon_seconds=30,
        consumed_features=("feat_a",),
    )
    ack = OrderAck(
        timestamp_ns=1_700_000_000_000_000_001,
        correlation_id="cid-2",
        sequence=2,
        symbol="AAA",
        order_id="o1",
        status=OrderAckStatus.FILLED,
        filled_quantity=10,
        fill_price=Decimal("100"),
        fees=Decimal("1.00"),
    )

    class _Rec:
        def of_type(self, t: type[object]) -> list[object]:
            if t is Signal:
                return [sig]
            if t is OrderAck:
                return [ack]
            return []

    pos = MagicMock()
    pos.realized_pnl = Decimal("50")
    pos.unrealized_pnl = Decimal("0")
    positions = MagicMock()
    positions.all_positions.return_value = {"AAA": pos}

    journal = MagicMock()
    journal.query.return_value = []

    orch = MagicMock()
    orch._positions = positions
    orch._trade_journal = journal

    cfg = PlatformConfig(symbols=frozenset({"AAA"}), mode=OperatingMode.BACKTEST)

    export_backtest_health_dir(
        out,
        recorder=_Rec(),
        orchestrator=orch,
        config=cfg,
        symbols=["AAA"],
        date_range="2024-01-01",
        platform_config_path=None,
        stress_cost_multiplier=1.0,
        ingest_events=100,
        data_source="test_source",
    )

    meta = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
    assert meta["alpha_name"] == "test_alpha"
    assert meta["universe"] == ["AAA"]
    assert meta["data_source"] == "test_source"
    assert (out / "signals.csv").is_file()
    assert (out / "execution_variants.json").is_file()
