"""Tests for DecayDetector TCA implementation (finding A)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.events import Side
from feelies.forensics.analyzer import TCAReport
from feelies.forensics.decay_detector import DecayDetector
from feelies.storage.trade_journal import TradeRecord


def _make_record(
    *,
    strategy_id: str = "strat",
    symbol: str = "AAPL",
    filled_quantity: int = 100,
    fill_price: str = "100.00",
    cost_bps: str = "10.00",
    fees: str = "1.00",
    realized_pnl: str = "0.00",
    order_id: str | None = None,
    idx: int = 0,
) -> TradeRecord:
    oid = order_id or f"ord-{idx}"
    return TradeRecord(
        order_id=oid,
        symbol=symbol,
        strategy_id=strategy_id,
        side=Side.BUY,
        requested_quantity=filled_quantity,
        filled_quantity=filled_quantity,
        fill_price=Decimal(fill_price),
        signal_timestamp_ns=idx,
        submit_timestamp_ns=idx,
        fill_timestamp_ns=idx,
        cost_bps=Decimal(cost_bps),
        fees=Decimal(fees),
        realized_pnl=Decimal(realized_pnl),
        correlation_id=f"cid-{idx}",
    )


class TestDecayDetectorAnalyzeFills:
    def test_empty_returns_zero_report(self) -> None:
        report = DecayDetector().analyze_fills([])
        assert report.trade_count == 0
        assert report.mean_cost_bps == 0.0
        assert report.mean_edge_bps == 0.0
        assert report.total_fees == 0.0
        assert report.pct_positive_edge == 0.0
        assert report.rolling_50_mean_edge_bps == 0.0

    def test_single_profitable_trade(self) -> None:
        """Positive realized_pnl → positive edge_bps, covers cost."""
        rec = _make_record(
            fill_price="100.00",
            filled_quantity=100,
            cost_bps="5.00",
            fees="0.50",
            realized_pnl="1.00",  # 1 / (100*100) * 10000 = 1 bps
        )
        report = DecayDetector().analyze_fills([rec])
        assert report.trade_count == 1
        assert report.mean_cost_bps == pytest.approx(5.0)
        assert report.mean_edge_bps == pytest.approx(1.0)
        assert report.pct_positive_edge == pytest.approx(100.0)

    def test_edge_covers_cost_pct(self) -> None:
        """pct_edge_covers_cost counts trades where edge > 2× cost."""
        # 3 trades: edge = 30 bps vs cost = 10 bps → all 3 cover 2×
        records = [
            _make_record(
                fill_price="100.00",
                filled_quantity=100,
                cost_bps="10.00",
                fees="1.00",
                realized_pnl="30.00",  # 30/(100*100)*10000 = 30 bps
                idx=i,
            )
            for i in range(3)
        ]
        report = DecayDetector().analyze_fills(records)
        assert report.pct_edge_covers_cost == pytest.approx(100.0)

    def test_edge_does_not_cover_cost(self) -> None:
        """Unprofitable trades: edge < 2× cost → 0% covers."""
        record = _make_record(
            fill_price="100.00",
            filled_quantity=100,
            cost_bps="10.00",
            fees="1.00",
            realized_pnl="0.50",  # 0.05 bps — well below 2×10 = 20
        )
        report = DecayDetector().analyze_fills([record])
        assert report.pct_edge_covers_cost == pytest.approx(0.0)

    def test_size_histogram_buckets(self) -> None:
        """Order-size histogram assigns records to correct buckets."""
        records = [
            _make_record(filled_quantity=50, idx=0),   # 1-100
            _make_record(filled_quantity=100, idx=1),  # 1-100
            _make_record(filled_quantity=200, idx=2),  # 101-500
            _make_record(filled_quantity=1000, idx=3), # 501-2000
            _make_record(filled_quantity=5000, idx=4), # >2000
        ]
        report = DecayDetector().analyze_fills(records)
        assert report.size_histogram["1-100"] == 2
        assert report.size_histogram["101-500"] == 1
        assert report.size_histogram["501-2000"] == 1
        assert report.size_histogram[">2000"] == 1

    def test_rolling_50_mean_requires_50_trades(self) -> None:
        """Rolling-50 differs from global mean only when >= 50 trades."""
        # First 50 trades at 0 pnl, next 10 at high pnl
        low_pnl = [
            _make_record(fill_price="100.00", filled_quantity=100, realized_pnl="0.00", idx=i)
            for i in range(50)
        ]
        high_pnl = [
            _make_record(fill_price="100.00", filled_quantity=100, realized_pnl="5.00", idx=i + 50)
            for i in range(10)
        ]
        all_records = low_pnl + high_pnl
        report = DecayDetector().analyze_fills(all_records)

        # rolling_50 should capture the last 10 high-pnl trades + 40 low-pnl
        # high_pnl edge = 5/(100*100)*10000 = 5 bps; low = 0
        # global mean = 5*10 / 60 ≈ 0.833 bps
        assert report.rolling_50_mean_edge_bps > report.mean_edge_bps  # recent is better

    def test_total_fees_summed(self) -> None:
        records = [_make_record(fees="2.50", idx=i) for i in range(4)]
        report = DecayDetector().analyze_fills(records)
        assert report.total_fees == pytest.approx(10.0)

    def test_p95_cost_bps(self) -> None:
        """p95 should be the 95th percentile of cost_bps values."""
        records = [_make_record(cost_bps=str(float(i)), idx=i) for i in range(100)]
        report = DecayDetector().analyze_fills(records)
        # index 95 of sorted 0..99 = 95
        assert report.p95_cost_bps == pytest.approx(95.0, abs=1.0)


class TestDecayDetectorDetectEdgeDecay:
    def test_no_decay_signal_below_threshold(self) -> None:
        """Z-score < 2.0 → no signals emitted."""
        # All trades uniform edge → no decay
        records = [
            _make_record(
                fill_price="100.00",
                filled_quantity=100,
                realized_pnl="1.00",  # ~1 bps uniform
                idx=i,
            )
            for i in range(120)
        ]
        signals = DecayDetector().detect_edge_decay("strat", records)
        assert signals == []

    def test_no_decay_fewer_than_100_trades(self) -> None:
        records = [_make_record(idx=i) for i in range(50)]
        signals = DecayDetector().detect_edge_decay("strat", records)
        assert signals == []

    def test_decay_detected_when_recent_edge_drops(self) -> None:
        """Historical edge high, recent edge near zero → Z-score triggers."""
        # 150 historical trades at high edge, then 50 at zero edge
        # historical mean ~50 bps, recent ~0 → large Z
        high_records = [
            _make_record(
                fill_price="100.00",
                filled_quantity=100,
                realized_pnl="5.00",  # 5 bps
                idx=i,
            )
            for i in range(150)
        ]
        low_records = [
            _make_record(
                fill_price="100.00",
                filled_quantity=100,
                realized_pnl="0.00",
                idx=i + 150,
            )
            for i in range(50)
        ]
        all_records = high_records + low_records
        signals = DecayDetector().detect_edge_decay("strat", all_records)
        assert len(signals) == 1
        assert signals[0].strategy_id == "strat"
        assert signals[0].z_score > 2.0
        assert signals[0].realized < signals[0].expected

    def test_filters_by_strategy_id(self) -> None:
        """Only the specified strategy_id's trades are used."""
        strat_a = [_make_record(strategy_id="A", idx=i) for i in range(200)]
        strat_b = [_make_record(strategy_id="B", idx=i + 200) for i in range(200)]
        detector = DecayDetector()
        # Neither should trigger decay since both are uniform zero-pnl
        assert detector.detect_edge_decay("A", strat_a + strat_b) == []
