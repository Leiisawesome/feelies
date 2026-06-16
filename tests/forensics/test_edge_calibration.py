"""Unit tests for edge realization calibration (calibrate + gate factors)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.events import Side
from feelies.forensics.edge_calibration import (
    EdgeCalibrationStore,
    build_edge_calibrations,
)
from feelies.storage.trade_journal import TradeRecord

_SEQ = 0


def _tr(strategy_id: str, realized_pnl: float, *, qty: int = 50, price: float = 100.0) -> TradeRecord:
    # edge_bps = realized_pnl / (price*qty) * 1e4 = realized_pnl * 2 (at 100/50)
    global _SEQ
    _SEQ += 1
    return TradeRecord(
        order_id=f"o{_SEQ}",
        symbol="APP",
        strategy_id=strategy_id,
        side=Side.BUY,
        requested_quantity=qty,
        filled_quantity=qty,
        fill_price=Decimal(str(price)),
        signal_timestamp_ns=_SEQ * 1000,
        submit_timestamp_ns=_SEQ * 1000 + 1,
        fill_timestamp_ns=_SEQ * 1000 + 2,
        cost_bps=Decimal("2"),
        fees=Decimal("0.1"),
        realized_pnl=Decimal(str(realized_pnl)),
        correlation_id=f"c{_SEQ}",
    )


def test_haircut_when_realized_below_disclosed() -> None:
    # constant realized edge 5 bps (pnl 2.5 -> 5 bps), disclosed 10 -> 0.5.
    fills = [_tr("a", 2.5) for _ in range(36)]
    cals = build_edge_calibrations(fills, {"a": 10.0})
    c = cals["a"]
    assert c.realized_edge_bps_mean == 5.0
    assert c.haircut_factor == 0.5
    assert c.lcb_factor == 0.5  # std 0 -> lcb == mean


def test_lcb_factor_below_haircut_when_variance() -> None:
    fills = [_tr("a", 2.0 if i % 2 else 3.0) for i in range(36)]  # edges 4 / 6
    cals = build_edge_calibrations(fills, {"a": 10.0}, z=1.0)
    c = cals["a"]
    assert c.realized_edge_bps_mean == pytest.approx(5.0)
    assert c.realized_edge_bps_std > 0.0
    assert c.lcb_factor < c.haircut_factor  # lower bound shrinks more
    assert c.lcb_factor < 0.5


def test_realized_above_disclosed_clamps_to_one() -> None:
    fills = [_tr("a", 10.0) for _ in range(36)]  # 20 bps vs disclosed 10
    cals = build_edge_calibrations(fills, {"a": 10.0})
    assert cals["a"].haircut_factor == 1.0
    assert cals["a"].lcb_factor == 1.0


def test_insufficient_fills_no_haircut() -> None:
    fills = [_tr("a", 0.0) for _ in range(10)]  # net zero edge but only 10 fills
    cals = build_edge_calibrations(fills, {"a": 10.0}, min_fills=30)
    assert cals["a"].haircut_factor == 1.0
    assert cals["a"].lcb_factor == 1.0


def test_missing_disclosed_edge_no_haircut() -> None:
    fills = [_tr("a", 0.0) for _ in range(40)]
    cals = build_edge_calibrations(fills, {})  # no disclosed edge for "a"
    assert cals["a"].lcb_factor == 1.0


def test_zero_realized_edge_factor_floor() -> None:
    fills = [_tr("a", 0.0) for _ in range(40)]
    cals = build_edge_calibrations(fills, {"a": 10.0})
    assert cals["a"].haircut_factor == 0.0
    assert cals["a"].lcb_factor == 0.0


def test_store_roundtrip_and_factors(tmp_path) -> None:
    fills = [_tr("a", 2.5) for _ in range(36)] + [_tr("b", 10.0) for _ in range(36)]
    cals = build_edge_calibrations(fills, {"a": 10.0, "b": 10.0})
    store = EdgeCalibrationStore(tmp_path / "edge_cal.json")
    store.save(cals, version="2026-06-16")

    reloaded = store.load()
    assert reloaded["a"].haircut_factor == 0.5
    assert reloaded["b"].lcb_factor == 1.0

    factors = store.factors(use_lcb=True)
    assert factors["a"] == 0.5
    assert factors["b"] == 1.0


def test_factors_empty_when_no_file(tmp_path) -> None:
    store = EdgeCalibrationStore(tmp_path / "missing.json")
    assert store.factors() == {}
    assert store.load() == {}
